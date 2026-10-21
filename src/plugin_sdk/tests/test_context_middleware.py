import pytest

from asgi_client import lifespan, request, websocket
from epicstaff_plugin.contracts.gateway_context import CONTEXT_HEADER
from epicstaff_plugin.gateway import (
    ContextUnavailableError,
    ContextVerifier,
    EpicStaffContextMiddleware,
    context_from_scope,
)


class RecordingApp:
    """A plugin app that answers with the context it was given, and accepts WebSockets."""

    def __init__(self):
        self.calls = 0
        self.lifespan_events = []

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                self.lifespan_events.append(message["type"])
                await send({"type": message["type"] + ".complete"})
                if message["type"] == "lifespan.shutdown":
                    return
        self.calls += 1
        context = context_from_scope(scope)
        if scope["type"] == "websocket":
            await receive()
            await send({"type": "websocket.accept"})
            await send({"type": "websocket.close", "code": 1000})
            return
        body = context.model_dump_json().encode()
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": body})


@pytest.fixture
def plugin_app():
    return RecordingApp()


@pytest.fixture
def protected(runtime, plugin_app):
    return EpicStaffContextMiddleware(plugin_app, ContextVerifier(runtime))


def test_a_request_with_a_valid_context_reaches_the_app_with_it(protected, plugin_app, signer):
    response = request(protected, "GET", "/api/ping", signer.headers("GET", "/api/ping"))

    assert response.status == 200
    assert response.json()["mode"] == "public"
    assert plugin_app.calls == 1


def test_a_request_without_a_context_is_refused_before_the_app(protected, plugin_app):
    response = request(protected, "GET", "/api/ping")

    assert (response.status, response.json()) == (401, {"code": "context_invalid"})
    assert response.headers["content-type"] == "application/json"
    assert plugin_app.calls == 0


def test_a_context_for_another_path_is_refused(protected, plugin_app, signer):
    response = request(protected, "GET", "/api/whoami", signer.headers("GET", "/api/ping"))

    assert response.status == 401
    assert plugin_app.calls == 0


def test_two_context_headers_are_refused(protected, plugin_app, signer):
    token = signer.issue("GET", "/api/ping")
    headers = [(CONTEXT_HEADER, token), (CONTEXT_HEADER.lower(), token)]

    assert request(protected, "GET", "/api/ping", headers).status == 401
    assert plugin_app.calls == 0


def test_the_header_name_is_matched_without_regard_to_case(protected, signer):
    headers = [("x-epicstaff-plugin-context", signer.issue("GET", "/api/ping"))]

    assert request(protected, "GET", "/api/ping", headers).status == 200


def test_the_underscore_spelling_of_the_header_is_not_a_context(protected, plugin_app, signer):
    headers = [("x_epicstaff_plugin_context", signer.issue("GET", "/api/ping"))]

    assert request(protected, "GET", "/api/ping", headers).status == 401
    assert plugin_app.calls == 0


def test_a_refusal_is_logged_with_its_reason_and_without_the_token(protected, signer, caplog):
    token = signer.issue("GET", "/api/ping")

    request(protected, "POST", "/api/ping", {CONTEXT_HEADER: token})

    assert "gateway context request_mismatch" in caplog.text
    assert token not in caplog.text


def test_a_websocket_with_a_valid_context_is_accepted(protected, plugin_app, signer):
    outcome = websocket(protected, "/api/live", signer.headers("GET", "/api/live"))

    assert outcome.accepted
    assert plugin_app.calls == 1


def test_a_websocket_without_a_context_is_closed_before_accept(protected, plugin_app):
    outcome = websocket(protected, "/api/live")

    assert (outcome.accepted, outcome.close_code) == (False, 1008)
    assert plugin_app.calls == 0


def test_a_websocket_without_a_context_gets_a_401_where_the_server_can_send_one(protected, plugin_app):
    outcome = websocket(protected, "/api/live", denial_response=True)

    assert (outcome.accepted, outcome.denial_status) == (False, 401)
    assert plugin_app.calls == 0


def test_lifespan_events_pass_through_without_a_context(protected, plugin_app):
    sent = lifespan(protected)

    assert plugin_app.lifespan_events == ["lifespan.startup", "lifespan.shutdown"]
    assert [message["type"] for message in sent] == ["lifespan.startup.complete", "lifespan.shutdown.complete"]


def test_the_middleware_uses_the_process_runtime_file_by_default(monkeypatch, runtime_file, plugin_app, signer):
    monkeypatch.setenv("EPICSTAFF_PLUGIN_RUNTIME_FILE", str(runtime_file))
    protected = EpicStaffContextMiddleware(plugin_app)

    assert request(protected, "GET", "/api/ping", signer.headers("GET", "/api/ping")).status == 200


def test_reading_the_context_of_an_unprotected_request_fails_loudly():
    with pytest.raises(ContextUnavailableError, match="epicstaff_plugin.serve"):
        context_from_scope({"type": "http", "path": "/api/ping"})
