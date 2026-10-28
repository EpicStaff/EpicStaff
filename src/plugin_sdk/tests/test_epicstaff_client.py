import asyncio
import json

import httpx
import pytest

from epicstaff_plugin.client import EpicStaffApiError, EpicStaffClient, ServiceAccountUnavailable
from epicstaff_plugin.contracts.service_account_api import PluginPerson, ServiceAccountInfo
from epicstaff_plugin.runtime import RuntimeConfig
from epicstaff_plugin.testing import service_account_key, write_runtime_file

ACME_KEY = service_account_key()
API = "http://epicstaff-api:8081/api/"


def _person(user_id, **changes):
    return {
        "user": {"id": user_id, "email": f"user{user_id}@acme.test", "name": f"User {user_id}"},
        "organization": {"id": 3, "name": "Acme"},
        "plugin_permissions": ["read"],
        "epicstaff_permissions": {"flows": ["read", "use"], "secrets": []},
        **changes,
    }


class FakeEpicStaff:
    """EpicStaff's API: answers with `routes[(method, path)]`, a response or a function of the request."""

    def __init__(self, routes=None):
        self.routes = routes or {}
        self.requests = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.routes.get((request.method, request.url.path))
        if answer is None:
            return httpx.Response(404, json={"status_code": 404, "code": "not_found", "message": "Not found."})
        return answer(request) if callable(answer) else answer


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def runtime_path(tmp_path, signer):
    path = tmp_path / "runtime.json"
    write_runtime_file(path, signer=signer, service_accounts={"3": {"key": ACME_KEY, "org_name": "Acme", "grant_state": "active"}})
    return path


@pytest.fixture
def fake():
    return FakeEpicStaff()


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def epicstaff(runtime_path, fake, clock):
    return EpicStaffClient(RuntimeConfig.load(runtime_path), transport=httpx.MockTransport(fake), clock=clock)


def run(coroutine):
    return asyncio.run(coroutine)


# --- Requests ---


def test_a_call_carries_the_key_the_organization_and_json(epicstaff, fake):
    fake.routes[("GET", "/api/graphs/")] = httpx.Response(200, json={"results": []})

    assert run(epicstaff.for_org(3).get("graphs/", params={"limit": 5})) == {"results": []}

    (sent,) = fake.requests
    assert str(sent.url) == API + "graphs/?limit=5"
    assert sent.headers["authorization"] == f"PluginKey {ACME_KEY}"
    assert sent.headers["x-organization-id"] == "3"
    assert sent.headers["accept"] == "application/json"
    assert "x-epicstaff-on-behalf-of" not in sent.headers


def test_a_call_on_behalf_of_a_person_names_them(epicstaff, fake):
    fake.routes[("POST", "/api/graphs/")] = httpx.Response(201, json={"id": 7})

    assert run(epicstaff.for_org(3).on_behalf_of(42).post("graphs/", {"name": "x"})) == {"id": 7}

    (sent,) = fake.requests
    assert sent.headers["x-epicstaff-on-behalf-of"] == "42"
    assert json.loads(sent.content) == {"name": "x"}


def test_a_leading_slash_in_the_path_stays_under_the_api(epicstaff, fake):
    fake.routes[("GET", "/api/graphs/")] = httpx.Response(200, json=[])

    run(epicstaff.for_org(3).get("/graphs/"))

    assert str(fake.requests[0].url) == API + "graphs/"


def test_an_empty_answer_is_none(epicstaff, fake):
    fake.routes[("DELETE", "/api/graphs/7/")] = httpx.Response(204)

    assert run(epicstaff.for_org(3).delete("graphs/7/")) is None


def test_the_environments_proxy_is_never_used(epicstaff, fake, monkeypatch):
    for variable in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "all_proxy"):
        monkeypatch.setenv(variable, "http://proxy.invalid:3128")
    fake.routes[("GET", "/api/graphs/")] = httpx.Response(200, json=[])

    assert run(epicstaff.for_org(3).get("graphs/")) == []
    assert len(fake.requests) == 1


def test_a_redirect_is_never_followed(epicstaff, fake):
    fake.routes[("GET", "/api/graphs/")] = httpx.Response(302, headers={"location": "https://elsewhere.example.com/"})

    response = run(epicstaff.for_org(3).request("GET", "graphs/"))

    assert response.status_code == 302
    assert len(fake.requests) == 1


def test_an_organization_without_a_service_account_is_unavailable(epicstaff, fake):
    with pytest.raises(ServiceAccountUnavailable) as raised:
        run(epicstaff.for_org(4).get("graphs/"))

    assert raised.value.org_id == 4
    assert fake.requests == []


@pytest.mark.parametrize("org_id", [0, -3, True, "3"])
def test_an_organization_id_is_a_positive_integer(epicstaff, org_id):
    with pytest.raises(ValueError):
        epicstaff.for_org(org_id)


@pytest.mark.parametrize("user_id", [0, -1, 2**63, True, "42"])
def test_on_behalf_of_takes_a_valid_user_id(epicstaff, user_id):
    with pytest.raises(ValueError):
        epicstaff.for_org(3).on_behalf_of(user_id)


# --- Key rotation ---


def test_a_401_with_a_key_the_node_has_since_replaced_is_retried_once_with_the_new_key(epicstaff, fake, runtime_path, signer):
    rotated = service_account_key()

    def answer(request):
        if request.headers["authorization"] == f"PluginKey {ACME_KEY}":
            # The node fetched new credentials while this call was on its way.
            write_runtime_file(runtime_path, signer=signer, service_accounts={"3": {"key": rotated, "org_name": "Acme", "grant_state": "active"}})
            return httpx.Response(401, json={"status_code": 401, "code": "service_account_not_authenticated", "message": "x"})
        return httpx.Response(200, json={"ok": True})

    fake.routes[("GET", "/api/graphs/")] = answer

    assert run(epicstaff.for_org(3).get("graphs/")) == {"ok": True}
    assert [request.headers["authorization"] for request in fake.requests] == [f"PluginKey {ACME_KEY}", f"PluginKey {rotated}"]


def test_a_401_with_the_current_key_is_raised_without_a_retry(epicstaff, fake):
    fake.routes[("GET", "/api/graphs/")] = httpx.Response(
        401, json={"status_code": 401, "code": "service_account_not_authenticated", "message": "Not authenticated."}
    )

    with pytest.raises(EpicStaffApiError) as raised:
        run(epicstaff.for_org(3).get("graphs/"))

    assert (raised.value.status, raised.value.code) == (401, "service_account_not_authenticated")
    assert len(fake.requests) == 1


def test_a_rotated_key_is_retried_only_once(epicstaff, fake, runtime_path, signer):
    def answer(request):
        write_runtime_file(runtime_path, signer=signer, service_accounts={"3": {"key": service_account_key(), "org_name": "Acme", "grant_state": "active"}})
        return httpx.Response(401, json={"status_code": 401, "code": "service_account_not_authenticated", "message": "x"})

    fake.routes[("GET", "/api/graphs/")] = answer

    with pytest.raises(EpicStaffApiError):
        run(epicstaff.for_org(3).get("graphs/"))

    assert len(fake.requests) == 2


def test_an_organization_dropped_from_the_runtime_file_after_a_401_is_unavailable(epicstaff, fake, runtime_path, signer):
    def answer(request):
        write_runtime_file(runtime_path, signer=signer, service_accounts={})
        return httpx.Response(401, json={"status_code": 401, "code": "service_account_not_authenticated", "message": "x"})

    fake.routes[("GET", "/api/graphs/")] = answer

    with pytest.raises(ServiceAccountUnavailable):
        run(epicstaff.for_org(3).get("graphs/"))


# --- Errors ---


def test_epicstaffs_error_envelope_becomes_the_error(epicstaff, fake):
    fake.routes[("POST", "/api/graphs/")] = httpx.Response(
        400,
        json={"status_code": 400, "code": "invalid", "message": "name: required", "errors": [{"loc": "name", "message": "required"}]},
    )

    with pytest.raises(EpicStaffApiError) as raised:
        run(epicstaff.for_org(3).post("graphs/", {}))

    error = raised.value
    assert (error.status, error.code, error.message) == (400, "invalid", "name: required")
    assert error.errors == [{"loc": "name", "message": "required"}]
    assert str(error) == "EpicStaff refused POST graphs/: 400 invalid: name: required"
    assert ACME_KEY not in str(error)


def test_an_answer_in_another_shape_keeps_its_text(epicstaff, fake):
    fake.routes[("POST", "/api/run-session/")] = httpx.Response(400, json={"graph_id": ["This field is required."]})

    with pytest.raises(EpicStaffApiError) as raised:
        run(epicstaff.for_org(3).post("run-session/", {}))

    assert raised.value.code is None
    assert "This field is required." in raised.value.message


def test_an_error_without_a_body_names_the_status(epicstaff, fake):
    fake.routes[("GET", "/api/graphs/")] = httpx.Response(502)

    with pytest.raises(EpicStaffApiError) as raised:
        run(epicstaff.for_org(3).get("graphs/"))

    assert (raised.value.status, raised.value.message) == (502, "Bad Gateway")


# --- The service account and people ---


def test_me_describes_the_service_account(epicstaff, fake):
    document = {
        "plugin": {"identifier": "weather", "version": "0.4.0"},
        "organization": {"id": 3, "name": "Acme"},
        "grant_state": "active",
        "access": {"flows": ["read", "create", "update", "use"]},
        "requests_per_minute": 120,
        "on_behalf_of": None,
    }
    fake.routes[("GET", "/api/plugin-runtime/me/")] = httpx.Response(200, json={**document, "added_later": 1})

    assert run(epicstaff.for_org(3).me()) == ServiceAccountInfo.model_validate(document)


def test_a_person_who_may_use_the_plugin_is_read_and_cached(epicstaff, fake, clock):
    fake.routes[("GET", "/api/plugin-runtime/people/42/")] = httpx.Response(200, json=_person(42))
    acme = epicstaff.for_org(3)

    person = run(acme.person(42))

    assert person == PluginPerson.model_validate(_person(42))
    assert person.has_epicstaff_permission("flows", "use")
    assert not person.has_epicstaff_permission("secrets", "read")
    clock.now += 29
    assert run(acme.person(42)) == person
    assert len(fake.requests) == 1
    clock.now += 2
    run(acme.person(42))
    assert len(fake.requests) == 2


def test_a_person_who_may_not_use_the_plugin_is_none(epicstaff, fake):
    fake.routes[("GET", "/api/plugin-runtime/people/43/")] = httpx.Response(
        404, json={"status_code": 404, "code": "person_not_found", "message": "No such person."}
    )

    assert run(epicstaff.for_org(3).person(43)) is None


def test_the_person_cache_can_be_turned_off(runtime_path, fake):
    fake.routes[("GET", "/api/plugin-runtime/people/42/")] = httpx.Response(200, json=_person(42))
    epicstaff = EpicStaffClient(RuntimeConfig.load(runtime_path), transport=httpx.MockTransport(fake), person_cache_seconds=0)

    run(epicstaff.for_org(3).person(42))
    run(epicstaff.for_org(3).person(42))

    assert len(fake.requests) == 2


@pytest.mark.parametrize("seconds", [-1, 31, 3600])
def test_a_person_is_never_cached_for_more_than_30_seconds(runtime_path, seconds):
    with pytest.raises(ValueError, match="at most 30 seconds"):
        EpicStaffClient(RuntimeConfig.load(runtime_path), person_cache_seconds=seconds)


def test_people_are_looked_up_in_batches_of_100(epicstaff, fake):
    def lookup(request):
        user_ids = json.loads(request.content)["user_ids"]
        # Only even ids may use the plugin.
        return httpx.Response(200, json={"people": [_person(user_id) for user_id in user_ids if user_id % 2 == 0]})

    fake.routes[("POST", "/api/plugin-runtime/people/lookup/")] = lookup
    wanted = list(range(250, 0, -1)) + [10, 10]

    people = run(epicstaff.for_org(3).people(wanted))

    assert [person.user.id for person in people] == list(range(2, 251, 2))
    assert [len(json.loads(request.content)["user_ids"]) for request in fake.requests] == [100, 100, 50]
    assert json.loads(fake.requests[0].content)["user_ids"] == list(range(1, 101))


def test_people_already_cached_are_not_asked_for_again(epicstaff, fake):
    fake.routes[("GET", "/api/plugin-runtime/people/42/")] = httpx.Response(200, json=_person(42))
    fake.routes[("POST", "/api/plugin-runtime/people/lookup/")] = httpx.Response(200, json={"people": []})
    acme = epicstaff.for_org(3)
    run(acme.person(42))

    assert [person.user.id for person in run(acme.people([42, 43]))] == [42]
    assert json.loads(fake.requests[-1].content) == {"user_ids": [43]}
    assert [person.user.id for person in run(acme.people([42, 43]))] == [42]
    assert len(fake.requests) == 2


def test_the_cache_is_per_organization(runtime_path, fake, signer):
    write_runtime_file(
        runtime_path,
        signer=signer,
        service_accounts={
            "3": {"key": ACME_KEY, "org_name": "Acme", "grant_state": "active"},
            "5": {"key": service_account_key(), "org_name": "Contoso", "grant_state": "active"},
        },
    )
    fake.routes[("GET", "/api/plugin-runtime/people/42/")] = lambda request: (
        httpx.Response(200, json=_person(42))
        if request.headers["x-organization-id"] == "3"
        else httpx.Response(404, json={"status_code": 404, "code": "person_not_found", "message": "x"})
    )
    epicstaff = EpicStaffClient(RuntimeConfig.load(runtime_path), transport=httpx.MockTransport(fake))

    assert run(epicstaff.for_org(3).person(42)) is not None
    assert run(epicstaff.for_org(5).person(42)) is None


# --- People in a gateway context ---


def test_the_client_for_a_user_context_acts_for_the_person_in_their_organization(epicstaff, signer):
    context = signer.context("GET", "/api/forecast", mode="user", user={"id": 42, "email": "ada@acme.test", "name": "Ada"}, org={"id": 3, "name": "Acme"})

    client = epicstaff.client_for_context(context)

    assert (client.org_id, client.on_behalf_of_user_id) == (3, 42)


def test_the_client_for_a_public_context_is_refused(epicstaff, signer):
    with pytest.raises(ValueError, match="no person"):
        epicstaff.client_for_context(signer.context("GET", "/api/ping"))


# --- Flows and files ---


def test_run_flow_starts_a_session_and_returns_its_id(epicstaff, fake):
    fake.routes[("POST", "/api/run-session/")] = httpx.Response(201, json={"session_id": 81})

    assert run(epicstaff.for_org(3).on_behalf_of(42).run_flow(7, {"city": "Paris"})) == 81
    assert json.loads(fake.requests[0].content) == {"graph_id": 7, "variables": {"city": "Paris"}}


def test_wait_for_session_polls_until_the_run_finished(epicstaff, fake, monkeypatch):
    statuses = iter(["pending", "run", "end"])
    fake.routes[("GET", "/api/sessions/81/")] = lambda request: httpx.Response(
        200, json={"id": 81, "status": (status := next(statuses)), "status_data": {"variables": {"forecast": 1}} if status == "end" else {}}
    )
    sleeps = []

    async def no_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    session = run(epicstaff.for_org(3).wait_for_session(81, timeout=10))

    assert (session.id, session.status, session.finished, session.succeeded) == (81, "end", True, True)
    assert session.variables == {"forecast": 1}
    assert sleeps == [2, 2]


def test_a_session_still_running_has_no_variables_yet(epicstaff, fake):
    fake.routes[("GET", "/api/sessions/81/")] = httpx.Response(200, json={"id": 81, "status": "run", "status_data": {"variables": {"partial": 1}}})

    session = run(epicstaff.for_org(3).session(81))

    assert (session.finished, session.variables) == (False, None)


def test_a_failed_session_is_finished_but_not_succeeded(epicstaff, fake):
    fake.routes[("GET", "/api/sessions/81/")] = httpx.Response(200, json={"id": 81, "status": "error", "status_data": {}})

    session = run(epicstaff.for_org(3).session(81))

    assert (session.finished, session.succeeded) == (True, False)


def test_wait_for_session_gives_up_after_the_timeout(epicstaff, fake):
    fake.routes[("GET", "/api/sessions/81/")] = httpx.Response(200, json={"id": 81, "status": "run", "status_data": {}})

    with pytest.raises(TimeoutError):
        run(epicstaff.for_org(3).wait_for_session(81, timeout=0.05, poll_seconds=0.01))


def test_upload_file_streams_the_bytes_into_the_folder(epicstaff, fake):
    fake.routes[("POST", "/api/storage/upload/stream")] = httpx.Response(200, json={"status": "DONE", "path": "weather/README.md"})

    answer = run(epicstaff.for_org(3).upload_file("weather", "README.md", b"# Weather\n"))

    assert answer["status"] == "DONE"
    (sent,) = fake.requests
    assert sent.url.params["path"] == "weather" and sent.url.params["filename"] == "README.md"
    assert sent.headers["content-type"] == "application/octet-stream"
    assert sent.content == b"# Weather\n"
