"""RequestAdmissionMiddleware in the project's middleware stack, driven over ASGI as uvicorn does.

The views behind it come from this module's URLconf. Sync tests driving asyncio.run on
purpose: a pure-async test that runs first in a session makes the session fixture
`flush_test_db_once` connect to the non-test database.
"""

import asyncio
import json
import sys
import threading

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.handlers.asgi import ASGIHandler
from django.http import HttpResponse, StreamingHttpResponse
from django.test import RequestFactory
from django.urls import path
from django.views.decorators.csrf import csrf_exempt

from django_app import asgi
from django_app.admission import RequestAdmissionMiddleware, retry_after_seconds

ALLOWED_ORIGIN = "http://allowed-frontend.test"
OTHER_ORIGIN = "http://other-site.test"
BUSY_ENVELOPE = {
    "status_code": 503,
    "code": "server_busy",
    "message": "The server is busy. Please retry shortly.",
}


class ViewState:
    """What the views did; a held request waits in its view, and a stream mid-way, for `release`.

    The sync view waits for `release_thread` in its own thread, as a DRF view runs.
    """

    def __init__(self):
        self.release = asyncio.Event()
        self.entered = 0
        self.running = 0
        self.most_running = 0
        self.release_thread = threading.Event()
        self.threads_running = 0


views = ViewState()


async def answer_ok(request):
    return HttpResponse("ok")


async def hold(request):
    views.entered += 1
    views.running += 1
    views.most_running = max(views.most_running, views.running)
    try:
        await views.release.wait()
    finally:
        views.running -= 1
    return HttpResponse("held")


def hold_in_thread(request):
    views.threads_running += 1
    try:
        # Bounded, so a failed test cannot leave the thread behind for good.
        views.release_thread.wait(timeout=10)
    finally:
        views.threads_running -= 1
    return HttpResponse("held in thread")


@csrf_exempt
async def echo_body_length(request):
    return HttpResponse(str(len(request.body)))


async def crash(request):
    raise RuntimeError("view crashed")


async def stream(request):
    async def chunks():
        yield b"first,"
        await views.release.wait()
        yield b"last"

    return StreamingHttpResponse(chunks())


urlpatterns = [
    path("ok/", answer_ok),
    path("held/", hold),
    path("held-in-thread/", hold_in_thread),
    path("echo/", echo_body_length),
    path("crash/", crash),
    path("stream/", stream),
    path("ht/", answer_ok),
]


@pytest.fixture(autouse=True)
def use_this_modules_urlconf(settings, monkeypatch):
    settings.ROOT_URLCONF = __name__
    monkeypatch.setattr(sys.modules[__name__], "views", ViewState())


@pytest.fixture
def build_handler(settings):
    """Build Django's ASGI handler, and so the middleware stack, under a cap and timeout."""

    def build(max_concurrent_requests: int, timeout: float | None) -> ASGIHandler:
        settings.MAX_CONCURRENT_REQUESTS = max_concurrent_requests
        settings.REQUEST_ADMISSION_TIMEOUT = timeout
        return ASGIHandler()

    return build


class CompleteBody:
    """A client that sends its whole request at once, then stays connected."""

    def __init__(self, body: bytes = b""):
        self._body = body
        self._sent = False

    async def __call__(self):
        if not self._sent:
            self._sent = True
            return {"type": "http.request", "body": self._body, "more_body": False}
        # Django cancels this wait once it has answered.
        await asyncio.Event().wait()


class TricklingBody:
    """A client that sends the first part of its body, and the rest only once `finish` is set."""

    def __init__(self):
        self.finish = asyncio.Event()
        self.parts_sent = 0

    async def __call__(self):
        self.parts_sent += 1
        if self.parts_sent == 1:
            return {"type": "http.request", "body": b"first part,", "more_body": True}
        if self.parts_sent == 2:
            await self.finish.wait()
            return {"type": "http.request", "body": b"last part", "more_body": False}
        await asyncio.Event().wait()


class DisconnectingClient:
    """A client that sends its request, then drops the connection once `disconnect` is set."""

    def __init__(self):
        self.disconnect = asyncio.Event()
        self._sent = False

    async def __call__(self):
        if not self._sent:
            self._sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await self.disconnect.wait()
        return {"type": "http.disconnect"}


def _scope(path, method, headers):
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver"), *headers],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }


async def _request(application, path, *, method="GET", headers=(), client=None, sent=None):
    """Send one request; return the ASGI messages it was answered with."""
    messages = [] if sent is None else sent

    async def send(message):
        messages.append(message)

    await application(_scope(path, method, headers), client or CompleteBody(), send)
    return messages


def _run(scenario):
    # A scenario that deadlocks fails here instead of hanging the run.
    return asyncio.run(asyncio.wait_for(scenario, timeout=20))


async def _until(condition):
    while not condition():
        await asyncio.sleep(0.005)


def _status(messages) -> int:
    return messages[0]["status"]


def _headers(messages) -> dict[str, str]:
    return {name.decode().lower(): value.decode() for name, value in messages[0]["headers"]}


def _body(messages) -> bytes:
    return b"".join(message.get("body", b"") for message in messages[1:])


async def _hold_every_slot(handler, count):
    held = [asyncio.create_task(_request(handler, "/held/")) for _ in range(count)]
    await _until(lambda: views.running == count)
    return held


async def _release(held):
    views.release.set()
    return await asyncio.gather(*held)


def test_a_client_still_sending_its_body_holds_no_slot(settings):
    # The real application, with the cap it was built with: a slot taken before Django has
    # read the body would let slow uploads lock every other request out.
    # It must never contend: its semaphore outlives this event loop and would bind to it.
    async def scenario():
        trickling_clients = [TricklingBody() for _ in range(settings.MAX_CONCURRENT_REQUESTS)]
        uploads = [
            asyncio.create_task(
                _request(asgi.application, "/echo/", method="POST", client=client)
            )
            for client in trickling_clients
        ]
        await _until(lambda: all(client.parts_sent == 2 for client in trickling_clients))

        answered_meanwhile = await _request(asgi.application, "/ok/")

        for client in trickling_clients:
            client.finish.set()
        return answered_meanwhile, await asyncio.gather(*uploads)

    answered_meanwhile, uploads = _run(scenario())

    assert _status(answered_meanwhile) == 200
    expected_length = str(len(b"first part,last part")).encode()
    assert [(_status(upload), _body(upload)) for upload in uploads] == [
        (200, expected_length)
    ] * settings.MAX_CONCURRENT_REQUESTS


def test_requests_past_the_cap_wait_and_run_as_slots_free_up(build_handler):
    async def scenario():
        handler = build_handler(max_concurrent_requests=2, timeout=5)
        requests = [asyncio.create_task(_request(handler, "/held/")) for _ in range(3)]
        await _until(lambda: views.entered == 2)
        await asyncio.sleep(0.2)
        entered_while_full = views.entered
        return entered_while_full, await _release(requests)

    entered_while_full, responses = _run(scenario())

    assert entered_while_full == 2
    assert [_status(response) for response in responses] == [200, 200, 200]
    assert views.most_running == 2


def test_a_request_still_waiting_at_the_timeout_gets_503_with_retry_after_without_running(
    build_handler,
):
    async def scenario():
        handler = build_handler(max_concurrent_requests=1, timeout=0.05)
        held = await _hold_every_slot(handler, 1)
        refused = await _request(handler, "/held/")
        entered = views.entered
        await _release(held)
        return refused, entered

    refused, entered = _run(scenario())

    assert entered == 1
    assert _status(refused) == 503
    assert _headers(refused)["retry-after"] == "1"
    assert _headers(refused)["content-type"] == "application/json"
    assert json.loads(_body(refused)) == BUSY_ENVELOPE



@pytest.mark.parametrize(
    ("admission_timeout", "expected"), [(0, 1), (0.05, 1), (1, 1), (1.2, 2), (2.5, 3), (5, 5)]
)
def test_retry_after_is_the_timeout_rounded_up_to_whole_seconds_and_at_least_one(
    admission_timeout, expected
):
    assert retry_after_seconds(admission_timeout) == expected

def test_a_crashing_view_gives_its_slot_back(build_handler):
    async def scenario():
        handler = build_handler(max_concurrent_requests=1, timeout=0.05)
        crashed = await _request(handler, "/crash/")
        return crashed, await _request(handler, "/ok/")

    crashed, next_request = _run(scenario())

    assert _status(crashed) == 500
    assert _status(next_request) == 200


def test_a_sync_view_left_running_by_a_disconnected_client_keeps_its_slot_until_it_ends(
    build_handler,
):
    # Django cancels the request when its client goes away, but the view's thread runs on
    # with its database connection, so the slot must stay taken until the thread ends.
    async def scenario():
        handler = build_handler(max_concurrent_requests=1, timeout=0.5)
        disconnecting_client = DisconnectingClient()
        abandoned = asyncio.create_task(
            _request(handler, "/held-in-thread/", client=disconnecting_client)
        )
        await _until(lambda: views.threads_running == 1)
        disconnecting_client.disconnect.set()
        # Let Django see the disconnect and cancel the request. Its ASGI call itself only
        # returns once the thread has ended.
        await asyncio.sleep(0.05)

        refused_while_the_thread_runs = await _request(handler, "/ok/")
        thread_still_running = views.threads_running

        views.release_thread.set()
        never_answered = await abandoned
        answered_once_it_ended = await _request(handler, "/ok/")
        return (
            never_answered,
            refused_while_the_thread_runs,
            thread_still_running,
            answered_once_it_ended,
        )

    never_answered, refused, thread_still_running, answered = _run(scenario())

    assert never_answered == []
    assert thread_still_running == 1
    assert _status(refused) == 503
    assert _status(answered) == 200


def test_a_cancelled_request_keeps_its_slot_until_the_thread_running_its_view_ends(settings):
    # Downstream as asgiref's sync_to_async can behave when cancelled: the await ends at
    # once while the thread goes on. Through the full stack above, this environment's
    # asgiref happens to delay the cancellation until the thread ends, which would hide
    # an early release.
    settings.MAX_CONCURRENT_REQUESTS = 1
    settings.REQUEST_ADMISSION_TIMEOUT = 0.2
    view_started = threading.Event()
    release_view = threading.Event()

    def blocking_view():
        view_started.set()
        release_view.wait(timeout=10)
        return HttpResponse("done")

    async def get_response(request):
        return await asyncio.get_running_loop().run_in_executor(None, blocking_view)

    async def scenario():
        middleware = RequestAdmissionMiddleware(get_response)
        request = RequestFactory().get("/api/graphs/")
        abandoned = asyncio.create_task(middleware(request))
        await _until(view_started.is_set)
        abandoned.cancel()
        with pytest.raises(asyncio.CancelledError):
            await abandoned

        refused_while_the_thread_runs = await middleware(request)
        release_view.set()
        answered_once_it_ended = await middleware(request)
        return refused_while_the_thread_runs, answered_once_it_ended

    refused, answered = _run(scenario())

    assert refused.status_code == 503
    assert answered.status_code == 200


def test_an_open_stream_holds_no_slot(build_handler):
    async def scenario():
        handler = build_handler(max_concurrent_requests=1, timeout=0.05)
        stream_messages = []
        streaming = asyncio.create_task(_request(handler, "/stream/", sent=stream_messages))
        await _until(lambda: _body(stream_messages) == b"first,")

        answered_while_streaming = await _request(handler, "/ok/")

        views.release.set()
        return answered_while_streaming, await streaming

    answered_while_streaming, stream_messages = _run(scenario())

    assert _status(answered_while_streaming) == 200
    assert (_status(stream_messages), _body(stream_messages)) == (200, b"first,last")


def test_a_client_disconnecting_while_waiting_leaves_the_capacity_at_the_cap(build_handler):
    async def scenario():
        # No timeout, so only the disconnect can end the wait.
        handler = build_handler(max_concurrent_requests=1, timeout=None)
        held = await _hold_every_slot(handler, 1)
        disconnecting_client = DisconnectingClient()
        waiter = asyncio.create_task(_request(handler, "/held/", client=disconnecting_client))
        await asyncio.sleep(0.05)
        disconnecting_client.disconnect.set()
        never_answered = await waiter
        await _release(held)

        # Exactly one slot again: the next request runs, and the one after it waits.
        views.release.clear()
        next_held = await _hold_every_slot(handler, 1)
        over_the_cap = asyncio.create_task(_request(handler, "/held/"))
        await asyncio.sleep(0.2)
        entered_with_one_over_the_cap = views.entered
        await _release([*next_held, over_the_cap])
        return never_answered, entered_with_one_over_the_cap

    never_answered, entered_with_one_over_the_cap = _run(scenario())

    assert never_answered == []
    # The first holder and the next request; the disconnected waiter never entered.
    assert entered_with_one_over_the_cap == 2
    assert views.entered == 3


def test_a_cors_preflight_is_answered_while_every_slot_is_taken(build_handler, settings):
    settings.CORS_ALLOWED_ORIGINS = [ALLOWED_ORIGIN]
    preflight_headers = [
        (b"origin", ALLOWED_ORIGIN.encode()),
        (b"access-control-request-method", b"POST"),
    ]

    async def scenario():
        handler = build_handler(max_concurrent_requests=1, timeout=0.05)
        held = await _hold_every_slot(handler, 1)
        preflight = await _request(handler, "/ok/", method="OPTIONS", headers=preflight_headers)
        await _release(held)
        return preflight

    preflight = _run(scenario())

    assert _status(preflight) == 200
    assert _headers(preflight)["access-control-allow-origin"] == ALLOWED_ORIGIN


@pytest.mark.parametrize(
    ("origin", "expected_allow_origin"), [(ALLOWED_ORIGIN, ALLOWED_ORIGIN), (OTHER_ORIGIN, None)]
)
def test_the_503_carries_cors_headers_for_an_allowed_origin_only(
    build_handler, settings, origin, expected_allow_origin
):
    settings.CORS_ALLOWED_ORIGINS = [ALLOWED_ORIGIN]

    async def scenario():
        handler = build_handler(max_concurrent_requests=1, timeout=0.05)
        held = await _hold_every_slot(handler, 1)
        refused = await _request(handler, "/ok/", headers=[(b"origin", origin.encode())])
        await _release(held)
        return refused

    refused = _run(scenario())

    assert _status(refused) == 503
    assert _headers(refused).get("access-control-allow-origin") == expected_allow_origin


def test_the_health_check_is_answered_while_every_slot_is_taken(build_handler):
    async def scenario():
        handler = build_handler(max_concurrent_requests=1, timeout=0.05)
        held = await _hold_every_slot(handler, 1)
        health_check = await _request(handler, "/ht/")
        await _release(held)
        return health_check

    assert _status(_run(scenario())) == 200


@pytest.fixture
def pool_max_size(settings, monkeypatch):
    """Set the database pool's max size a request handler sees, restored after the test."""
    pool = settings.DATABASES["default"]["OPTIONS"]["pool"]
    return lambda max_size: monkeypatch.setitem(pool, "max_size", max_size)


def test_a_request_handler_accepts_a_cap_below_its_pool(build_handler, pool_max_size):
    pool_max_size(4)

    build_handler(max_concurrent_requests=3, timeout=5)


@pytest.mark.parametrize(
    ("max_concurrent_requests", "pool_size"),
    [
        # Equal leaves no connection for streams, websockets and uploads.
        (4, 4),
        # The Redis workers' pool, with the default cap: fine for a manage.py process that
        # serves no HTTP, refused once one builds a request handler.
        (8, 2),
    ],
)
def test_a_request_handler_refuses_a_cap_not_below_its_pool_naming_both_values(
    build_handler, pool_max_size, max_concurrent_requests, pool_size
):
    pool_max_size(pool_size)

    with pytest.raises(ImproperlyConfigured) as error:
        build_handler(max_concurrent_requests=max_concurrent_requests, timeout=5)

    assert str(error.value) == (
        "DJANGO_SGI_MAX_CONCURRENT_REQUESTS must be below DJANGO_DB_POOL_MAX_SIZE, to leave "
        "connections for streams, websockets and uploads; got "
        f"DJANGO_SGI_MAX_CONCURRENT_REQUESTS={max_concurrent_requests} and "
        f"DJANGO_DB_POOL_MAX_SIZE={pool_size}."
    )


def test_a_request_handler_refuses_a_pool_without_a_max_size(build_handler, pool_max_size):
    pool_max_size(None)

    with pytest.raises(ImproperlyConfigured, match="DJANGO_DB_POOL_MAX_SIZE=None"):
        build_handler(max_concurrent_requests=8, timeout=5)
