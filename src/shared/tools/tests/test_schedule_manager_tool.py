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
        # Regression test (EST-3285): graph_id may be stored/read as a
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
                json={
                    "id": 1,
                    "graph": 4,
                    "node_name": payload["node_name"],
                    "schedule": payload["schedule"],
                },
            )

        _mock_httpx_client(monkeypatch, handler)

        result = schedule_main(
            action="create",
            run_mode="once",
            start_date_time="2026-07-06T09:15:00",
        )

        assert "Error" not in result

    def test_create_invalid_graph_id_returns_readable_error(self):
        _configure(schedule_module, graph_id="not-a-number")

        result = schedule_main(
            action="create",
            run_mode="once",
            start_date_time="2026-07-06T09:15:00",
        )

        assert result.startswith("Error:")
        assert "graph_id" in result

    def test_create_applies_jitter_on_round_boundary(self, monkeypatch):
        _configure(schedule_module)
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json as _json

            payload = _json.loads(request.content)
            captured["start"] = payload["schedule"]["start_date_time"]
            return httpx.Response(
                201,
                json={
                    "id": 1,
                    "graph": 7,
                    "node_name": "n",
                    "schedule": payload["schedule"],
                },
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
                json={
                    "id": 1,
                    "graph": 7,
                    "node_name": "n",
                    "schedule": payload["schedule"],
                },
            )

        _mock_httpx_client(monkeypatch, handler)

        schedule_main(
            action="create",
            run_mode="once",
            start_date_time="2026-07-06T09:00:00",
            apply_jitter=False,
        )

        assert captured["start"] == "2026-07-06T09:00:00"

    def test_create_repeat_requires_unit_with_every(self):
        _configure(schedule_module)

        result = schedule_main(
            action="create",
            run_mode="repeat",
            start_date_time="2026-07-06T09:15:00",
            every=2,
        )

        assert result.startswith("Error:")
        assert "every" in result and "unit" in result

    def test_create_missing_start_date_time(self):
        _configure(schedule_module)

        result = schedule_main(action="create", run_mode="once")

        assert result.startswith("Error:")
        assert "start_date_time" in result

    def test_create_after_n_runs_requires_max_runs(self):
        _configure(schedule_module)

        result = schedule_main(
            action="create",
            run_mode="once",
            start_date_time="2026-07-06T09:15:00",
            end_type="after_n_runs",
        )

        assert result.startswith("Error:")
        assert "max_runs" in result


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
        # Regression test (EST-3285): graph_id may be stored/read as a float
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
                            "end": {
                                "type": "never",
                                "date_time": None,
                                "max_runs": None,
                            },
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

    def test_update_missing_schedule_id(self):
        _configure(schedule_module)

        result = schedule_main(action="update")

        assert result.startswith("Error:")
        assert "schedule_id" in result

    def test_update_rejects_cross_graph_schedule(self, monkeypatch):
        _configure(schedule_module, graph_id=7)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"id": 10, "graph": 999, "node_name": "other-org"}
            )

        _mock_httpx_client(monkeypatch, handler)

        result = schedule_main(action="update", schedule_id=10, is_active=False)

        assert result.startswith("Error:")
        assert "another graph" in result

    def test_update_unknown_schedule_id(self, monkeypatch):
        _configure(schedule_module)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        _mock_httpx_client(monkeypatch, handler)

        result = schedule_main(action="update", schedule_id=9999, is_active=False)

        assert result.startswith("Error:")
        assert "not found" in result


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

    def test_delete_missing_schedule_id(self):
        _configure(schedule_module)

        result = schedule_main(action="delete")

        assert result.startswith("Error:")
        assert "schedule_id" in result

    def test_delete_rejects_cross_graph_schedule(self, monkeypatch):
        _configure(schedule_module, graph_id=7)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"id": 10, "graph": 999})

        _mock_httpx_client(monkeypatch, handler)

        result = schedule_main(action="delete", schedule_id=10)

        assert result.startswith("Error:")
        assert "another graph" in result

    def test_delete_unknown_schedule_id(self, monkeypatch):
        _configure(schedule_module)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        _mock_httpx_client(monkeypatch, handler)

        result = schedule_main(action="delete", schedule_id=9999)

        assert result.startswith("Error:")
        assert "not found" in result


class TestScheduleManagerToolGeneral:
    def test_invalid_action_returns_error(self):
        _configure(schedule_module)

        result = schedule_main(action="destroy")

        assert result.startswith("Error:")
        assert "action" in result

    def test_missing_graph_id_returns_error(self):
        schedule_module.api_key = "test-key"

        result = schedule_main(action="list")

        assert result.startswith("Error:")
        assert "graph_id" in result

    def test_missing_api_key_returns_error(self):
        schedule_module.graph_id = 7

        result = schedule_main(action="list")

        assert result.startswith("Error:")
        assert "api_key" in result

    def test_stray_config_kwargs_are_absorbed_and_globals_win(self, monkeypatch):
        """Regression test (EST-3285 smoke test): python_code.global_kwargs
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


class TestScheduleManagerToolHeaders:
    """EST-3285: org_id (server-side resolved from Graph.org_id, injected by
    the crew engine) must be sent as X-Organization-Id so
    /schedule-trigger-nodes/ (org-scoped) doesn't 400 with
    org_context_required."""

    def test_headers_includes_org_header_when_org_id_injected(self):
        schedule_module.org_id = 42

        headers = schedule_module._headers("test-key")

        assert headers["X-Organization-Id"] == "42"
        assert headers["X-Api-Key"] == "test-key"

    def test_headers_omits_org_header_when_org_id_absent(self):
        headers = schedule_module._headers("test-key")

        assert "X-Organization-Id" not in headers
        assert headers["X-Api-Key"] == "test-key"
