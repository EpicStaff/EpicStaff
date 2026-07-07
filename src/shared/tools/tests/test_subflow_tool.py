import httpx
import pytest

from conftest import load_tool_main

subflow_module = load_tool_main("subflow_tool")
subflow_main = subflow_module.main


@pytest.fixture(autouse=True)
def _reset_globals():
    # Mirrors how the sandbox injects PythonCodeToolConfig.configuration
    # values (and the crew-engine-injected `session_id`) as bare module
    # globals (see wrap_code() in sandbox/dynamic_venv_executor_chain.py and
    # global_kwargs["session_id"] in crew_node.py) — set/clear them directly
    # on the loaded module instead of passing them as function arguments.
    names = ["graph_id", "api_key", "api_base_url", "poll_timeout_s", "session_id"]
    for name in names:
        if hasattr(subflow_module, name):
            delattr(subflow_module, name)
    yield
    for name in names:
        if hasattr(subflow_module, name):
            delattr(subflow_module, name)


_ORIGINAL_HTTPX_CLIENT = httpx.Client


def _mock_httpx_client(monkeypatch, handler):
    def _fake_client(**kwargs):
        return _ORIGINAL_HTTPX_CLIENT(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "Client", _fake_client)


def _configure(module, graph_id=42, api_key="test-key", poll_timeout_s=None):
    module.graph_id = graph_id
    module.api_key = api_key
    if poll_timeout_s is not None:
        module.poll_timeout_s = poll_timeout_s


class TestSubflowTool:
    def test_happy_path_runs_subflow_and_returns_output(self, monkeypatch):
        _configure(subflow_module)
        subflow_module.session_id = 100  # caller session

        calls = {"gets": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["X-Api-Key"] == "test-key"

            if request.method == "GET" and request.url.path == "/api/sessions/100/":
                # recursion-guard lookup of the caller's own session — a
                # different graph than the target, no parent
                return httpx.Response(
                    200, json={"id": 100, "graph": 7, "parent_session": None}
                )

            if request.method == "POST" and request.url.path == "/api/run-session/":
                import json as _json

                payload = _json.loads(request.content)
                assert payload["graph_id"] == 42
                assert payload["variables"] == {"topic": "cats"}
                assert payload["parent_session_id"] == 100
                return httpx.Response(201, json={"session_id": 555})

            if request.method == "GET" and request.url.path == "/api/sessions/555/":
                calls["gets"] += 1
                return httpx.Response(
                    200,
                    json={
                        "id": 555,
                        "graph": 42,
                        "parent_session": 100,
                        "status": "end",
                        "variables": {"result": "meow"},
                    },
                )

            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        _mock_httpx_client(monkeypatch, handler)

        result = subflow_main(input_variables={"topic": "cats"})

        assert result == '{"result": "meow"}'
        assert calls["gets"] == 1

    def test_missing_graph_id_returns_error(self):
        subflow_module.api_key = "test-key"

        result = subflow_main(input_variables={})

        assert result.startswith("Error:")
        assert "graph_id" in result

    def test_missing_api_key_returns_error(self):
        subflow_module.graph_id = 42

        result = subflow_main(input_variables={})

        assert result.startswith("Error:")
        assert "api_key" in result

    def test_unknown_graph_id_returns_error(self, monkeypatch):
        _configure(subflow_module, graph_id=9999)

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path == "/api/run-session/":
                return httpx.Response(
                    404, json={"message": "Provided graph does not exist"}
                )
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        _mock_httpx_client(monkeypatch, handler)

        result = subflow_main(input_variables={})

        assert result.startswith("Error:")
        assert "404" in result

    def test_self_reference_recursion_guard(self, monkeypatch):
        # Caller session's own graph_id is the same as the target graph_id.
        _configure(subflow_module, graph_id=42)
        subflow_module.session_id = 100

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET" and request.url.path == "/api/sessions/100/":
                return httpx.Response(
                    200, json={"id": 100, "graph": 42, "parent_session": None}
                )
            raise AssertionError(
                f"should not reach run-session for a direct self-reference: "
                f"{request.method} {request.url}"
            )

        _mock_httpx_client(monkeypatch, handler)

        result = subflow_main(input_variables={})

        assert result.startswith("Error:")
        assert "recursion" in result

    def test_ancestor_cycle_recursion_guard(self, monkeypatch):
        # graph 42 appears two levels up the parent_session chain.
        _configure(subflow_module, graph_id=42)
        subflow_module.session_id = 300

        sessions = {
            300: {"id": 300, "graph": 9, "parent_session": 200},
            200: {"id": 200, "graph": 42, "parent_session": 100},
        }

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET" and request.url.path.startswith(
                "/api/sessions/"
            ):
                sid = int(request.url.path.rstrip("/").rsplit("/", 1)[1])
                return httpx.Response(200, json=sessions[sid])
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        _mock_httpx_client(monkeypatch, handler)

        result = subflow_main(input_variables={})

        assert result.startswith("Error:")
        assert "recursion" in result

    def test_max_depth_guard(self, monkeypatch):
        _configure(subflow_module, graph_id=42)
        subflow_module.session_id = 1000

        # A chain of 7 distinct graphs (deeper than MAX_SUBFLOW_DEPTH), none
        # of which is the target graph_id -- should be stopped by the depth
        # cap rather than looping forever.
        chain_len = 7
        sessions = {}
        for i in range(chain_len):
            sid = 1000 - i
            parent = sid - 1 if i < chain_len - 1 else None
            sessions[sid] = {"id": sid, "graph": 500 + i, "parent_session": parent}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET" and request.url.path.startswith(
                "/api/sessions/"
            ):
                sid = int(request.url.path.rstrip("/").rsplit("/", 1)[1])
                return httpx.Response(200, json=sessions[sid])
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        _mock_httpx_client(monkeypatch, handler)

        result = subflow_main(input_variables={})

        assert result.startswith("Error:")
        assert "depth" in result or "deep" in result

    def test_subflow_failure_surfaced_as_readable_error(self, monkeypatch):
        _configure(subflow_module, graph_id=42)
        # No caller session_id -> recursion guard / parent linkage skipped.

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path == "/api/run-session/":
                return httpx.Response(201, json={"session_id": 777})

            if request.method == "GET" and request.url.path == "/api/sessions/777/":
                return httpx.Response(
                    200,
                    json={
                        "id": 777,
                        "graph": 42,
                        "parent_session": None,
                        "status": "error",
                        "status_data": {"reason": "graph entrypoint missing"},
                        "variables": {},
                    },
                )

            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        _mock_httpx_client(monkeypatch, handler)

        result = subflow_main(input_variables={})

        assert result.startswith("Error:")
        assert "graph entrypoint missing" in result

    def test_missing_session_id_logs_warning_but_is_non_fatal(self, monkeypatch):
        # No caller session_id -> recursion guard / parent linkage disabled,
        # but the tool must still run successfully and just warn about it.
        _configure(subflow_module, graph_id=42)

        from loguru import logger

        warnings = []
        sink_id = logger.add(lambda msg: warnings.append(msg), level="WARNING")

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path == "/api/run-session/":
                import json as _json

                payload = _json.loads(request.content)
                assert "parent_session_id" not in payload
                return httpx.Response(201, json={"session_id": 999})

            if request.method == "GET" and request.url.path == "/api/sessions/999/":
                return httpx.Response(
                    200,
                    json={
                        "id": 999,
                        "graph": 42,
                        "parent_session": None,
                        "status": "end",
                        "variables": {"result": "ok"},
                    },
                )

            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        _mock_httpx_client(monkeypatch, handler)

        try:
            result = subflow_main(input_variables={})
        finally:
            logger.remove(sink_id)

        assert result == '{"result": "ok"}'
        assert any("session_id" in str(w) for w in warnings)

    def test_stray_config_kwargs_are_absorbed_and_globals_win(self, monkeypatch):
        """Regression test (EST-3285 smoke test): python_code.global_kwargs
        folds user_input config (graph_id/api_key) into func_kwargs, so
        main() may also receive them as kwargs even though main()'s real
        signature only has 'input_variables'. The globals remain the source
        of truth; the stray kwargs must be swallowed by **kwargs without a
        TypeError."""
        _configure(subflow_module, graph_id=42, api_key="real-key")

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["X-Api-Key"] == "real-key"
            if request.method == "POST" and request.url.path == "/api/run-session/":
                import json as _json

                payload = _json.loads(request.content)
                assert payload["graph_id"] == 42
                return httpx.Response(201, json={"session_id": 321})
            if request.method == "GET" and request.url.path == "/api/sessions/321/":
                return httpx.Response(
                    200,
                    json={
                        "id": 321,
                        "graph": 42,
                        "parent_session": None,
                        "status": "end",
                        "variables": {"result": "ok"},
                    },
                )
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        _mock_httpx_client(monkeypatch, handler)

        result = subflow_main(
            input_variables={}, graph_id=999, api_key="stray-kwarg-key"
        )

        assert result == '{"result": "ok"}'

    def test_poll_timeout_returns_readable_error(self, monkeypatch):
        _configure(subflow_module, graph_id=42, poll_timeout_s=0)

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path == "/api/run-session/":
                return httpx.Response(201, json={"session_id": 888})

            if request.method == "GET" and request.url.path == "/api/sessions/888/":
                return httpx.Response(
                    200,
                    json={
                        "id": 888,
                        "graph": 42,
                        "parent_session": None,
                        "status": "run",
                        "variables": {},
                    },
                )

            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        _mock_httpx_client(monkeypatch, handler)

        result = subflow_main(input_variables={})

        assert result.startswith("Error:")
        assert "did not finish" in result
