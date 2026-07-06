import json

import httpx
import pytest

from conftest import load_tool_main

spawn_module = load_tool_main("spawn_agent_tool")
spawn_main = spawn_module.main


@pytest.fixture(autouse=True)
def _reset_globals():
    # Mirrors how the sandbox injects PythonCodeToolConfig.configuration
    # values (and the crew-engine-injected `session_id`) as bare module
    # globals -- set/clear them directly on the loaded module instead of
    # passing them as function arguments.
    names = ["api_key", "api_base_url", "default_llm_config_id", "poll_timeout_s", "session_id"]
    for name in names:
        if hasattr(spawn_module, name):
            delattr(spawn_module, name)
    yield
    for name in names:
        if hasattr(spawn_module, name):
            delattr(spawn_module, name)


_ORIGINAL_HTTPX_CLIENT = httpx.Client


def _mock_httpx_client(monkeypatch, handler):
    def _fake_client(**kwargs):
        return _ORIGINAL_HTTPX_CLIENT(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "Client", _fake_client)


def _configure(module, api_key="test-key", default_llm_config_id=7, poll_timeout_s=None):
    module.api_key = api_key
    module.default_llm_config_id = default_llm_config_id
    if poll_timeout_s is not None:
        module.poll_timeout_s = poll_timeout_s


CREATE_ID_SEQUENCE = {
    "/api/agents/": 101,
    "/api/crews/": 201,
    "/api/tasks/": 301,
    "/api/graphs/": 401,
    "/api/startnodes/": 501,
    "/api/crewnodes/": 601,
    "/api/endnodes/": 701,
}


def _default_handler(deletes, sub_session_id=555, sub_status="end", sub_variables=None,
                      sub_token_usage=None, sub_status_data=None, run_session_status=201,
                      caller_session_response=None, run_session_message="boom"):
    sub_variables = sub_variables if sub_variables is not None else {"result": "42"}
    sub_token_usage = sub_token_usage if sub_token_usage is not None else {"total_tokens": 123}

    edge_counter = {"n": 800}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Api-Key"] == "test-key"
        path = request.url.path
        method = request.method

        if method == "GET" and path.startswith("/api/sessions/") and path != f"/api/sessions/{sub_session_id}/":
            if caller_session_response is not None:
                return httpx.Response(200, json=caller_session_response)
            raise AssertionError(f"unexpected caller-session GET: {path}")

        if method == "POST" and path in CREATE_ID_SEQUENCE:
            return httpx.Response(201, json={"id": CREATE_ID_SEQUENCE[path]})

        if method == "POST" and path == "/api/edges/":
            edge_counter["n"] += 1
            return httpx.Response(201, json={"id": edge_counter["n"]})

        if method == "POST" and path == "/api/run-session/":
            if run_session_status not in (200, 201):
                return httpx.Response(run_session_status, json={"message": run_session_message})
            return httpx.Response(run_session_status, json={"session_id": sub_session_id})

        if method == "GET" and path == f"/api/sessions/{sub_session_id}/":
            data = {
                "id": sub_session_id,
                "graph": CREATE_ID_SEQUENCE["/api/graphs/"],
                "parent_session": None,
                "status": sub_status,
                "variables": sub_variables,
                "token_usage": sub_token_usage,
            }
            if sub_status_data:
                data["status_data"] = sub_status_data
            return httpx.Response(200, json=data)

        if method == "DELETE":
            deletes.append(path)
            return httpx.Response(204)

        raise AssertionError(f"unexpected request: {method} {path}")

    return handler


class TestSpawnAgentTool:
    def test_happy_path_runs_spawn_and_returns_output_and_token_usage(self, monkeypatch):
        _configure(spawn_module)
        deletes = []
        handler = _default_handler(deletes)
        _mock_httpx_client(monkeypatch, handler)

        result = spawn_main(prompt="Summarize the news")

        parsed = json.loads(result)
        assert parsed["output"] == "42"
        assert parsed["token_usage"] == {"total_tokens": 123}
        assert parsed["session_id"] == 555

        # Every transient row created must be cleaned up.
        assert "/api/graphs/401/" in deletes
        assert "/api/tasks/301/" in deletes
        assert "/api/crews/201/" in deletes
        assert "/api/agents/101/" in deletes

    def test_llm_config_override_is_passed_through(self, monkeypatch):
        _configure(spawn_module, default_llm_config_id=7)
        deletes = []
        seen_agent_payload = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path == "/api/agents/":
                seen_agent_payload.update(json.loads(request.content))
                return httpx.Response(201, json={"id": 101})
            return _default_handler(deletes)(request)

        _mock_httpx_client(monkeypatch, handler)

        result = spawn_main(prompt="Do the thing", llm_config_id=99)

        assert not result.startswith("Error:")
        assert seen_agent_payload["llm_config"] == 99

    def test_missing_prompt_returns_error(self):
        spawn_module.api_key = "test-key"
        spawn_module.default_llm_config_id = 7

        result = spawn_main(prompt=None)

        assert result.startswith("Error:")
        assert "prompt" in result

    def test_missing_api_key_returns_error(self):
        spawn_module.default_llm_config_id = 7

        result = spawn_main(prompt="hello")

        assert result.startswith("Error:")
        assert "api_key" in result

    def test_missing_llm_config_returns_error(self):
        spawn_module.api_key = "test-key"

        result = spawn_main(prompt="hello")

        assert result.startswith("Error:")
        assert "LLM config" in result

    def test_max_depth_guard(self, monkeypatch):
        _configure(spawn_module)
        spawn_module.session_id = 1000

        chain_len = 7
        sessions = {}
        for i in range(chain_len):
            sid = 1000 - i
            parent = sid - 1 if i < chain_len - 1 else None
            sessions[sid] = {"id": sid, "graph": 900 + i, "parent_session": parent}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET" and request.url.path.startswith("/api/sessions/"):
                sid = int(request.url.path.rstrip("/").rsplit("/", 1)[1])
                return httpx.Response(200, json=sessions[sid])
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        _mock_httpx_client(monkeypatch, handler)

        result = spawn_main(prompt="hello")

        assert result.startswith("Error:")
        assert "depth" in result or "deep" in result

    def test_spawn_failure_surfaced_as_readable_error(self, monkeypatch):
        _configure(spawn_module)
        deletes = []
        handler = _default_handler(
            deletes,
            sub_status="error",
            sub_status_data={"reason": "agent crashed"},
        )
        _mock_httpx_client(monkeypatch, handler)

        result = spawn_main(prompt="hello")

        assert result.startswith("Error:")
        assert "agent crashed" in result
        # Cleanup must still happen on failure.
        assert "/api/graphs/401/" in deletes
        assert "/api/agents/101/" in deletes

    def test_poll_timeout_returns_readable_error(self, monkeypatch):
        _configure(spawn_module, poll_timeout_s=0)
        deletes = []
        handler = _default_handler(deletes, sub_status="run")
        _mock_httpx_client(monkeypatch, handler)

        result = spawn_main(prompt="hello")

        assert result.startswith("Error:")
        assert "did not finish" in result
        # Cleanup must still happen on timeout.
        assert "/api/graphs/401/" in deletes

    def test_run_session_failure_still_cleans_up_transient_rows(self, monkeypatch):
        _configure(spawn_module)
        deletes = []
        handler = _default_handler(deletes, run_session_status=404)
        _mock_httpx_client(monkeypatch, handler)

        result = spawn_main(prompt="hello")

        assert result.startswith("Error:")
        assert "/api/graphs/401/" in deletes
        assert "/api/tasks/301/" in deletes
        assert "/api/crews/201/" in deletes
        assert "/api/agents/101/" in deletes

    def test_cross_org_parent_session_spawn_fails(self, monkeypatch):
        _configure(spawn_module)
        spawn_module.session_id = 42
        deletes = []
        handler = _default_handler(
            deletes,
            run_session_status=400,
            run_session_message=(
                "Parent session does not belong to the same organization "
                "as the target graph."
            ),
            caller_session_response={"id": 42, "graph": 900, "parent_session": None},
        )
        _mock_httpx_client(monkeypatch, handler)

        result = spawn_main(prompt="hello")

        assert result.startswith("Error:")
        assert "does not match the spawned graph's organization" in result
        assert "known multi-org limitation" in result
        # Must not leak the raw HTTP status/body.
        assert "400" not in result
        # Cleanup must still happen when the run-session call is rejected.
        assert "/api/graphs/401/" in deletes
        assert "/api/tasks/301/" in deletes
        assert "/api/crews/201/" in deletes
        assert "/api/agents/101/" in deletes

    def test_parent_session_id_included_in_run_session_payload_when_session_id_set(
        self, monkeypatch
    ):
        _configure(spawn_module)
        spawn_module.session_id = 42
        deletes = []
        seen_run_session_payload = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path == "/api/run-session/":
                seen_run_session_payload.update(json.loads(request.content))
            return _default_handler(
                deletes, caller_session_response={"id": 42, "graph": 900, "parent_session": None}
            )(request)

        _mock_httpx_client(monkeypatch, handler)

        result = spawn_main(prompt="hello")

        assert not result.startswith("Error:")
        assert seen_run_session_payload.get("parent_session_id") == 42

    def test_missing_session_id_logs_warning_but_is_non_fatal(self, monkeypatch):
        _configure(spawn_module)
        # No caller session_id -> recursion guard / parent linkage disabled,
        # but the tool must still run successfully and just warn about it.

        from loguru import logger

        warnings = []
        sink_id = logger.add(lambda msg: warnings.append(msg), level="WARNING")

        deletes = []
        seen_run_session_payload = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path == "/api/run-session/":
                seen_run_session_payload.update(json.loads(request.content))
            return _default_handler(deletes)(request)

        _mock_httpx_client(monkeypatch, handler)

        try:
            result = spawn_main(prompt="hello")
        finally:
            logger.remove(sink_id)

        assert not result.startswith("Error:")
        assert "parent_session_id" not in seen_run_session_payload
        assert any("session_id" in str(w) for w in warnings)
