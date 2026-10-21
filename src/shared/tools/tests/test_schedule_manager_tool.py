import json

import httpx
import pytest

from conftest import load_tool_main

schedule_module = load_tool_main("schedule_manager_tool")
schedule_main = schedule_module.main


@pytest.fixture(autouse=True)
def _reset_globals():
    # Mirrors how the sandbox injects PythonCodeToolConfig.configuration
    # values as bare module globals (see subflow_tool tests for the same
    # pattern).
    names = ["graph_id", "api_key", "api_base_url", "org_id"]
    for name in names:
        if hasattr(schedule_module, name):
            delattr(schedule_module, name)
    yield
    for name in names:
        if hasattr(schedule_module, name):
            delattr(schedule_module, name)


_ORIGINAL_HTTPX_CLIENT = httpx.Client


def _mock_httpx_client(monkeypatch, handler):
    def _fake_client(**kwargs):
        return _ORIGINAL_HTTPX_CLIENT(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "Client", _fake_client)


def _configure(module, graph_id=7, api_key="test-key"):
    module.graph_id = graph_id
    module.api_key = api_key


_AUTHORSHIP_KEYS = {"created_by", "last_edited_by", "last_edited_at"}

_SCHEDULE_BLOCK = {
    "run_mode": "once",
    "timezone": "UTC",
    "start_date_time": "2026-07-06T09:15:00",
    "interval": {"every": None, "unit": None, "weekdays": None},
    "end": {"type": "never", "date_time": None, "max_runs": None},
}


def _schedule_with_authorship(schedule_id, node_name="nightly"):
    return {
        "id": schedule_id,
        "graph": 7,
        "node_name": node_name,
        "is_active": True,
        "schedule": _SCHEDULE_BLOCK,
        "created_by": {
            "id": 3,
            "display_name": "Jane Colleague",
            "avatar_url": "http://djangoapp:8000/media/avatars/3.png",
        },
        "last_edited_by": {
            "id": 4,
            "display_name": "John Colleague",
            "avatar_url": "http://djangoapp:8000/media/avatars/4.png",
        },
        "last_edited_at": "2026-07-05T12:00:00Z",
    }


def _assert_no_authorship_anywhere(value):
    if isinstance(value, dict):
        assert not _AUTHORSHIP_KEYS & value.keys(), value
        for nested in value.values():
            _assert_no_authorship_anywhere(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_authorship_anywhere(nested)


def _assert_schedule_fields_kept(returned, schedule_id, node_name="nightly"):
    assert returned["id"] == schedule_id
    assert returned["graph"] == 7
    assert returned["node_name"] == node_name
    assert returned["schedule"] == _SCHEDULE_BLOCK


class TestScheduleManagerToolCreate:
    def test_create_happy_path(self, monkeypatch):
        _configure(schedule_module)

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["X-Api-Key"] == "test-key"
            assert request.method == "POST"
            assert request.url.path == "/api/schedule-trigger-nodes/"
            import json as _json

            payload = _json.loads(request.content)
            assert payload["graph"] == 7
            assert payload["schedule"]["run_mode"] == "repeat"
            assert payload["schedule"]["interval"] == {
                "every": 2,
                "unit": "hours",
                "weekdays": [],
            }
            return httpx.Response(
                201,
                json={
                    "id": 55,
                    "graph": 7,
                    "node_name": payload["node_name"],
                    "is_active": True,
                    "schedule": payload["schedule"],
                },
            )

        _mock_httpx_client(monkeypatch, handler)

        result = schedule_main(
            action="create",
            run_mode="repeat",
            start_date_time="2026-07-06T09:15:00",
            every=2,
            unit="hours",
        )

        assert "Error" not in result
        assert '"id": 55' in result

    def test_create_coerces_float_graph_id_to_int(self, monkeypatch):
        # Regression test: graph_id may be stored/read as a
        # float-ish value ("4.0" string or 4.0 float); the outgoing create
        # payload's `graph` field must be a plain int (Django rejects "4.0"
        # with a ValidationError on the `graph` choice field).
        _configure(schedule_module, graph_id="4.0")

        def handler(request: httpx.Request) -> httpx.Response:
            import json as _json

            payload = _json.loads(request.content)
            assert payload["graph"] == 4
            return httpx.Response(
                201,
                json={"id": 1, "graph": 4, "node_name": payload["node_name"], "schedule": payload["schedule"]},
            )

        _mock_httpx_client(monkeypatch, handler)

        result = schedule_main(
            action="create",
            run_mode="once",
            start_date_time="2026-07-06T09:15:00",
        )

        assert "Error" not in result

    def test_create_applies_jitter_on_round_boundary(self, monkeypatch):
        _configure(schedule_module)
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json as _json

            payload = _json.loads(request.content)
            captured["start"] = payload["schedule"]["start_date_time"]
            return httpx.Response(
                201,
                json={"id": 1, "graph": 7, "node_name": "n", "schedule": payload["schedule"]},
            )

        _mock_httpx_client(monkeypatch, handler)

        result = schedule_main(
            action="create",
            run_mode="once",
            start_date_time="2026-07-06T09:00:00",
            end_type="never",
        )

        assert "Error" not in result
        assert captured["start"] != "2026-07-06T09:00:00"
        assert "jittered" in result

    def test_create_skips_jitter_when_disabled(self, monkeypatch):
        _configure(schedule_module)
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json as _json

            payload = _json.loads(request.content)
            captured["start"] = payload["schedule"]["start_date_time"]
            return httpx.Response(
                201,
                json={"id": 1, "graph": 7, "node_name": "n", "schedule": payload["schedule"]},
            )

        _mock_httpx_client(monkeypatch, handler)

        schedule_main(
            action="create",
            run_mode="once",
            start_date_time="2026-07-06T09:00:00",
            apply_jitter=False,
        )

        assert captured["start"] == "2026-07-06T09:00:00"

    def test_create_result_omits_authorship(self, monkeypatch):
        _configure(schedule_module)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(201, json=_schedule_with_authorship(55))

        _mock_httpx_client(monkeypatch, handler)

        result = schedule_main(
            action="create",
            node_name="nightly",
            run_mode="once",
            start_date_time="2026-07-06T09:15:00",
        )

        returned = json.loads(result)
        _assert_no_authorship_anywhere(returned)
        _assert_schedule_fields_kept(returned["created"], 55)


class TestScheduleManagerToolList:
    def test_list_happy_path(self, monkeypatch):
        _configure(schedule_module)

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert request.url.path == "/api/schedule-trigger-nodes/"
            assert request.url.params["graph"] == "7"
            return httpx.Response(
                200,
                json={
                    "count": 2,
                    "results": [
                        {"id": 1, "graph": 7, "node_name": "a"},
                        {"id": 2, "graph": 7, "node_name": "b"},
                    ],
                },
            )

        _mock_httpx_client(monkeypatch, handler)

        result = schedule_main(action="list")

        assert '"count_returned": 2' in result
        assert '"truncated": false' in result

    def test_list_coerces_float_graph_id_to_int(self, monkeypatch):
        # Regression test: graph_id may be stored/read as a float
        # (e.g. 4.0) by the config layer; the tool must send an int in the
        # `?graph=` query param, not "4.0", or Django rejects the filter.
        _configure(schedule_module, graph_id=4.0)

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["graph"] == "4"
            return httpx.Response(200, json={"count": 0, "results": []})

        _mock_httpx_client(monkeypatch, handler)

        result = schedule_main(action="list")

        assert "Error" not in result
        assert '"graph_id": 4' in result

    def test_list_truncates_large_result_set(self, monkeypatch):
        _configure(schedule_module)

        many = [{"id": i, "graph": 7, "node_name": f"s{i}"} for i in range(150)]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"count": 150, "results": many})

        _mock_httpx_client(monkeypatch, handler)

        result = schedule_main(action="list")

        assert '"count_returned": 100' in result
        assert '"truncated": true' in result

    def test_list_results_omit_authorship(self, monkeypatch):
        _configure(schedule_module)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "count": 2,
                    "results": [
                        _schedule_with_authorship(1, node_name="a"),
                        _schedule_with_authorship(2, node_name="b"),
                    ],
                },
            )

        _mock_httpx_client(monkeypatch, handler)

        result = schedule_main(action="list")

        returned = json.loads(result)
        _assert_no_authorship_anywhere(returned)
        assert returned["count_returned"] == 2
        _assert_schedule_fields_kept(returned["schedules"][0], 1, node_name="a")
        _assert_schedule_fields_kept(returned["schedules"][1], 2, node_name="b")


class TestScheduleManagerToolUpdate:
    def test_update_toggle_is_active_only(self, monkeypatch):
        _configure(schedule_module)

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(
                    200,
                    json={
                        "id": 10,
                        "graph": 7,
                        "node_name": "existing",
                        "is_active": True,
                        "schedule": {
                            "run_mode": "once",
                            "timezone": "UTC",
                            "start_date_time": "2026-07-06T09:00:00",
                            "interval": None,
                            "end": {"type": "never", "date_time": None, "max_runs": None},
                        },
                    },
                )
            import json as _json

            payload = _json.loads(request.content)
            assert "schedule" not in payload
            assert payload == {"is_active": False}
            return httpx.Response(200, json={"id": 10, "graph": 7, "is_active": False})

        _mock_httpx_client(monkeypatch, handler)

        result = schedule_main(action="update", schedule_id=10, is_active=False)

        assert "Error" not in result

    def test_update_result_omits_authorship(self, monkeypatch):
        _configure(schedule_module)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_schedule_with_authorship(10))

        _mock_httpx_client(monkeypatch, handler)

        result = schedule_main(action="update", schedule_id=10, node_name="nightly")

        returned = json.loads(result)
        _assert_no_authorship_anywhere(returned)
        _assert_schedule_fields_kept(returned["updated"], 10)


class TestScheduleManagerToolDelete:
    def test_delete_happy_path(self, monkeypatch):
        _configure(schedule_module)

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(200, json={"id": 10, "graph": 7})
            assert request.method == "DELETE"
            return httpx.Response(204)

        _mock_httpx_client(monkeypatch, handler)

        result = schedule_main(action="delete", schedule_id=10)

        assert '"deleted": 10' in result


class TestScheduleManagerToolGeneral:
    def test_stray_config_kwargs_are_absorbed_and_globals_win(self, monkeypatch):
        """Regression test (smoke test): python_code.global_kwargs
        folds user_input config (graph_id/api_key) into func_kwargs, so
        main() may also receive them as kwargs. The globals remain the
        source of truth; the stray kwargs must be swallowed by **kwargs
        without a TypeError."""
        _configure(schedule_module, graph_id=7, api_key="real-key")

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["X-Api-Key"] == "real-key"
            return httpx.Response(200, json={"count": 0, "results": []})

        _mock_httpx_client(monkeypatch, handler)

        result = schedule_main(action="list", graph_id=999, api_key="stray-kwarg-key")

        assert "Error" not in result


def _refuse_requests(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"no request expected, got {request.method} {request.url}")

    _mock_httpx_client(monkeypatch, handler)


@pytest.mark.parametrize(
    ("config", "kwargs", "mentions"),
    [
        ({"graph_id": "not-a-number"}, {"action": "create", "run_mode": "once", "start_date_time": "2026-07-06T09:15:00"}, ("graph_id",)),
        ({}, {"action": "create", "run_mode": "repeat", "start_date_time": "2026-07-06T09:15:00", "every": 2}, ("every", "unit")),
        ({}, {"action": "create", "run_mode": "once"}, ("start_date_time",)),
        ({}, {"action": "create", "run_mode": "once", "start_date_time": "2026-07-06T09:15:00", "end_type": "after_n_runs"}, ("max_runs",)),
        ({}, {"action": "update"}, ("schedule_id",)),
        ({}, {"action": "delete"}, ("schedule_id",)),
        ({}, {"action": "destroy"}, ("action",)),
        ({"graph_id": None}, {"action": "list"}, ("graph_id",)),
        ({"api_key": None}, {"action": "list"}, ("api_key",)),
    ],
    ids=[
        "bad-graph-id", "repeat-every-without-unit", "no-start", "after-n-runs-without-max",
        "update-without-id", "delete-without-id", "unknown-action", "no-graph-id", "no-api-key",
    ],
)
def test_invalid_call_is_explained_without_calling_django(monkeypatch, config, kwargs, mentions):
    for name, value in {"graph_id": 7, "api_key": "test-key", **config}.items():
        if value is not None:
            setattr(schedule_module, name, value)
    _refuse_requests(monkeypatch)

    result = schedule_main(**kwargs)

    assert result.startswith("Error:")
    for word in mentions:
        assert word in result


@pytest.mark.parametrize("action", ["update", "delete"])
@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(200, json={"id": 10, "graph": 999, "node_name": "other-org"}), "another graph"),
        (httpx.Response(404), "not found"),
    ],
    ids=["another-graphs-schedule", "unknown-schedule"],
)
def test_schedule_outside_this_graph_is_not_touched(monkeypatch, action, response, message):
    _configure(schedule_module, graph_id=7)
    methods = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return response

    _mock_httpx_client(monkeypatch, handler)

    result = schedule_main(action=action, schedule_id=10, is_active=False)

    assert result.startswith("Error:")
    assert message in result
    assert methods == ["GET"]


@pytest.mark.parametrize(("org_id", "expected_header"), [(42, "42"), (None, None)], ids=["org-injected", "no-org"])
def test_requests_carry_the_api_key_and_the_injected_org(monkeypatch, org_id, expected_header):
    """org_id (resolved server-side from Graph.org_id, injected by crew) must be sent
    as X-Organization-Id: /schedule-trigger-nodes/ is org-scoped."""
    _configure(schedule_module)
    if org_id is not None:
        schedule_module.org_id = org_id
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers)
        return httpx.Response(200, json={"count": 0, "results": []})

    _mock_httpx_client(monkeypatch, handler)

    schedule_main(action="list")

    (headers,) = seen
    assert headers["X-Api-Key"] == "test-key"
    assert headers.get("X-Organization-Id") == expected_header
