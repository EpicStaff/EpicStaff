import asyncio
import json
import time

import httpx
import pytest

from asgi_client import request
from conftest import ISSUER
from epicstaff_plugin.client import EpicStaffClient
from epicstaff_plugin.contracts.gateway_context import CONTEXT_HEADER
from epicstaff_plugin.contracts.hook_api import (
    HOOK_ASSERTION_GRACE_SECONDS,
    HOOK_HEADER,
    MAX_HOOK_BODY_BYTES,
    HookRequest,
    encode_hook_body,
    hook_body_sha256,
)
from epicstaff_plugin.hooks import (
    HookAssertionVerifier,
    HookDispatchMiddleware,
    HookRegistry,
)
from epicstaff_plugin.runtime import RuntimeConfig
from epicstaff_plugin.runtime.signing_keys import SigningKeys
from epicstaff_plugin.serve import build_app
from epicstaff_plugin.testing import ContextSigner, HookSigner, write_runtime_file

ACME = {"id": 3, "name": "Acme"}


class RecordingApp:
    """The plugin's own app: records every request that reaches it."""

    def __init__(self):
        self.paths = []

    async def __call__(self, scope, receive, send):
        self.paths.append(scope["path"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"app"})


class RecordingHandler:
    def __init__(self, error=None, delay=0.0):
        self.calls = []
        self.events = []
        self.error = error
        self.delay = delay

    async def __call__(self, hook_request, epicstaff):
        self.calls.append((hook_request, epicstaff))
        self.events.append(("start", hook_request.job_id))
        await asyncio.sleep(self.delay)
        self.events.append(("end", hook_request.job_id))
        if self.error is not None:
            raise self.error


@pytest.fixture
def hooks(signer):
    return HookSigner(signer)


@pytest.fixture
def plugin_app():
    return RecordingApp()


@pytest.fixture
def handler():
    return RecordingHandler()


@pytest.fixture
def registry(handler):
    registry = HookRegistry()
    registry.on_install(handler)
    return registry


@pytest.fixture
def served(plugin_app, runtime, registry):
    return build_app(
        plugin_app,
        runtime,
        hooks=registry,
        epicstaff=EpicStaffClient(runtime, transport=httpx.MockTransport(lambda request: httpx.Response(500))),
    )


def _post(app, call, *, path=None, body=None, headers=None):
    return request(app, "POST", path or call.path, headers if headers is not None else call.headers, call.body if body is None else body)


def _rejected(response, reason):
    return response.status == 401 and response.json() == {
        "status": "failed",
        "error": {"message": f"hook assertion rejected: {reason}"},
    }


def _claims_for(call, **changes):
    return {**call.claims.model_dump(mode="json"), **changes}


# --- Answers ---


def test_a_hook_that_returns_answers_done(served, hooks, handler, plugin_app):
    call = hooks.call("install", org=ACME, job_id=41, attempt=2)

    response = _post(served, call)

    assert (response.status, response.json()) == (200, {"status": "done"})
    assert response.headers["content-type"] == "application/json"
    (hook_request, epicstaff), = handler.calls
    assert hook_request == call.request
    assert (hook_request.job_id, hook_request.attempt, hook_request.org.id) == (41, 2, 3)
    assert (epicstaff.org_id, epicstaff.on_behalf_of_user_id) == (3, None)
    assert plugin_app.paths == []


def test_a_hook_that_raises_answers_failed_with_the_first_line(plugin_app, runtime, hooks):
    failing = RecordingHandler(error=RuntimeError("the flow could not be created\nTraceback detail"))
    registry = HookRegistry()
    registry.on_install(failing)

    response = _post(build_app(plugin_app, runtime, hooks=registry), hooks.call("install"))

    assert (response.status, response.json()) == (
        500,
        {"status": "failed", "error": {"message": "the flow could not be created"}},
    )


def test_a_failure_message_is_cut_to_2000_characters(plugin_app, runtime, hooks):
    registry = HookRegistry()
    registry.on_install(RecordingHandler(error=ValueError("x" * 5000)))

    response = _post(build_app(plugin_app, runtime, hooks=registry), hooks.call("install"))

    assert response.json()["error"]["message"] == "x" * 2000


def test_an_exception_without_a_message_is_named(plugin_app, runtime, hooks):
    registry = HookRegistry()
    registry.on_install(RecordingHandler(error=KeyError()))

    response = _post(build_app(plugin_app, runtime, hooks=registry), hooks.call("install"))

    assert response.json()["error"]["message"] == "KeyError"


def test_a_kind_without_a_handler_answers_501(served, hooks):
    response = _post(served, hooks.call("upgrade", previous_version="0.1.0"))

    assert (response.status, response.json()) == (
        501,
        {"status": "failed", "error": {"message": "this plugin has no upgrade hook"}},
    )


@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE", "HEAD"])
def test_a_hook_path_answers_only_post(served, hooks, handler, plugin_app, method):
    call = hooks.call("install")

    response = request(served, method, call.path, call.headers)

    assert response.status == 405
    assert response.headers["allow"] == "POST"
    assert handler.calls == [] and plugin_app.paths == []


# --- Refusals: the handler never runs ---


def test_a_call_without_an_assertion_is_rejected(served, hooks, handler):
    assert _rejected(_post(served, hooks.call("install"), headers={}), "missing")
    assert handler.calls == []


def test_a_call_with_two_assertions_is_rejected(served, hooks, handler):
    call = hooks.call("install")
    headers = [(HOOK_HEADER, call.headers[HOOK_HEADER])] * 2

    assert _rejected(_post(served, call, headers=headers), "ambiguous")
    assert handler.calls == []


def test_a_bad_signature_is_rejected(served, hooks, signer, handler):
    call = hooks.call("install")
    impostor = HookSigner(ContextSigner(plugin_identifier="weather", issuer=ISSUER))
    forged = impostor.sign(call.claims, headers={"kid": signer.kid})

    assert _rejected(_post(served, call, headers={HOOK_HEADER: forged}), "bad_signature")
    assert handler.calls == []


def test_a_gateway_context_is_rejected_as_a_hook_assertion(served, hooks, signer, handler):
    call = hooks.call("install")
    context = signer.issue("POST", call.path)

    assert _rejected(_post(served, call, headers={HOOK_HEADER: context}), "wrong_type")
    assert handler.calls == []


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"aud": "another-plugin"}, "wrong_audience"),
        ({"iss": "https://elsewhere.example.com"}, "wrong_issuer"),
        ({"job_id": 42}, "body_mismatch"),
        ({"attempt": 3}, "body_mismatch"),
        ({"org_id": 5}, "body_mismatch"),
        ({"body_sha256": "0" * 64}, "body_digest_mismatch"),
        ({"kind": "upgrade"}, "wrong_kind"),
        ({"jti": "not-hex"}, "invalid_claims"),
    ],
)
def test_claims_that_do_not_match_are_rejected(served, hooks, handler, changes, reason):
    call = hooks.call("install", org=ACME, job_id=41)
    assertion = hooks.sign(_claims_for(call, **changes))

    assert _rejected(_post(served, call, headers={HOOK_HEADER: assertion}), reason)
    assert handler.calls == []


def test_an_install_call_posted_to_another_hook_path_is_rejected(served, hooks, handler):
    call = hooks.call("install")

    assert _rejected(_post(served, call, path="/_epicstaff/hooks/upgrade"), "wrong_kind")
    assert handler.calls == []


def test_a_body_other_than_the_one_signed_is_rejected(served, hooks, handler):
    call = hooks.call("install", org=ACME)

    assert _rejected(_post(served, call, body=call.body + b" "), "body_digest_mismatch")
    assert handler.calls == []


def test_a_signed_body_that_names_another_job_is_rejected(served, hooks, handler):
    call = hooks.call("install", org=ACME, job_id=41)
    other_body = encode_hook_body(HookRequest.model_validate({**json.loads(call.body), "job_id": 42}))
    assertion = hooks.sign(_claims_for(call, body_sha256=hook_body_sha256(other_body)))

    response = _post(served, call, body=other_body, headers={HOOK_HEADER: assertion})

    assert _rejected(response, "body_mismatch")
    assert handler.calls == []


def test_a_signed_body_that_is_not_a_hook_request_is_rejected(served, hooks, handler):
    call = hooks.call("install")
    body = b'{"format": 1}'

    response = _post(served, call, body=body, headers={HOOK_HEADER: hooks.sign(_claims_for(call, body_sha256=hook_body_sha256(body)))})

    assert _rejected(response, "invalid_body")
    assert handler.calls == []


def test_a_body_over_the_cap_is_rejected_unread(served, hooks, handler):
    call = hooks.call("install")

    assert _rejected(_post(served, call, body=b" " * (MAX_HOOK_BODY_BYTES + 1)), "body_too_large")
    assert handler.calls == []


def test_an_expired_assertion_is_rejected(served, hooks, handler):
    timeout = 60
    issued_at = int(time.time()) - timeout - HOOK_ASSERTION_GRACE_SECONDS - 31
    call = hooks.call("install", timeout_seconds=timeout, issued_at=issued_at)

    assert _rejected(_post(served, call), "expired")
    assert handler.calls == []


def test_an_assertion_within_the_clock_leeway_is_accepted(served, hooks, handler):
    timeout = 60
    issued_at = int(time.time()) - timeout - HOOK_ASSERTION_GRACE_SECONDS - 20
    call = hooks.call("install", timeout_seconds=timeout, issued_at=issued_at)

    assert _post(served, call).status == 200


# --- Placement: health, hooks, context, app ---


def test_hook_paths_never_reach_the_context_check_or_the_app(served, hooks, signer, plugin_app, caplog):
    call = hooks.call("install")
    with_context = {**call.headers, CONTEXT_HEADER: signer.issue("POST", call.path)}

    assert _post(served, call, headers=with_context).status == 200
    assert _rejected(_post(served, call, headers={CONTEXT_HEADER: signer.issue("POST", call.path)}), "missing")
    assert plugin_app.paths == []
    assert "gateway context" not in caplog.text


def test_health_still_answers(served):
    assert request(served, "GET", "/_epicstaff/health").json() == {"status": "ok"}


def test_other_paths_still_need_a_gateway_context(served, signer, hooks, plugin_app):
    call = hooks.call("install")

    assert request(served, "POST", "/api/places", call.headers, call.body).status == 401
    assert request(served, "POST", "/_epicstaff/hooks/install/", call.headers, call.body).status == 401
    assert request(served, "GET", "/api/places", signer.headers("GET", "/api/places")).status == 200
    assert plugin_app.paths == ["/api/places"]


# --- Concurrency ---


async def _call_async(app, call):
    sent = []
    pending = [{"type": "http.request", "body": call.body, "more_body": False}]

    async def receive():
        if pending:
            return pending.pop(0)
        await asyncio.sleep(3600)

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": call.path,
        "headers": [(name.lower().encode(), value.encode()) for name, value in call.headers.items()],
        "query_string": b"",
    }
    await app(scope, receive, send)
    return next(message["status"] for message in sent if message["type"] == "http.response.start")


def _run_together(app, *calls):
    async def run():
        return await asyncio.gather(*(_call_async(app, call) for call in calls))

    return asyncio.run(run())


def test_two_deliveries_for_one_organization_run_one_after_the_other(plugin_app, runtime, hooks):
    slow = RecordingHandler(delay=0.05)
    registry = HookRegistry()
    registry.on_install(slow)
    app = build_app(plugin_app, runtime, hooks=registry)

    statuses = _run_together(app, hooks.call("install", org=ACME, job_id=41), hooks.call("install", org=ACME, job_id=41, attempt=2))

    assert statuses == [200, 200]
    assert slow.events == [("start", 41), ("end", 41), ("start", 41), ("end", 41)]


def test_deliveries_for_two_organizations_run_side_by_side(plugin_app, runtime, hooks):
    slow = RecordingHandler(delay=0.05)
    registry = HookRegistry()
    registry.on_install(slow)
    app = build_app(plugin_app, runtime, hooks=registry)

    _run_together(app, hooks.call("install", org=ACME, job_id=41), hooks.call("install", org={"id": 5, "name": "Contoso"}, job_id=42))

    assert [event for event, _ in slow.events] == ["start", "start", "end", "end"]


# --- Keys ---


def test_a_hook_signed_with_a_key_the_runtime_file_does_not_list_yet_is_verified_after_a_download(tmp_path, signer, plugin_app):
    path = tmp_path / "runtime.json"
    write_runtime_file(path, signer=signer)
    rotated = ContextSigner(plugin_identifier="weather", plugin_version="0.2.0", issuer=ISSUER)
    downloads = []

    def fetch_jwks(url):
        downloads.append(url)
        return rotated.jwks.model_dump_json().encode()

    runtime = RuntimeConfig.load(path)
    handler = RecordingHandler()
    registry = HookRegistry()
    registry.on_install(handler)
    app = HookDispatchMiddleware(
        plugin_app, HookAssertionVerifier(SigningKeys(runtime, fetch_jwks=fetch_jwks)), registry, EpicStaffClient(runtime)
    )

    assert _post(app, HookSigner(rotated).call("install")).status == 200
    assert downloads == ["http://epicstaff-api:8081/api/plugin-public/jwks/"]
    assert len(handler.calls) == 1


# --- Registration ---


def test_a_kind_takes_one_handler():
    registry = HookRegistry()
    registry.on_install(RecordingHandler())

    with pytest.raises(ValueError, match="already has a handler"):
        registry.on_install(RecordingHandler())


def test_a_handler_must_be_async():
    def install(request, epicstaff):
        return None

    with pytest.raises(TypeError, match="async"):
        HookRegistry().on_install(install)


def test_an_unknown_kind_cannot_be_registered():
    async def handler(request, epicstaff):
        return None

    with pytest.raises(ValueError, match="not a hook kind"):
        HookRegistry().register("uninstall", handler)


def test_each_kind_has_its_registration_method():
    async def install(request, epicstaff):
        return None

    async def upgrade(request, epicstaff):
        return None

    async def org_removed(request, epicstaff):
        return None

    registry = HookRegistry()
    assert registry.on_install(install) is install
    assert registry.on_upgrade(upgrade) is upgrade
    assert registry.on_org_removed(org_removed) is org_removed
    assert [registry.handler(kind) for kind in ("install", "upgrade", "org_removed")] == [install, upgrade, org_removed]
