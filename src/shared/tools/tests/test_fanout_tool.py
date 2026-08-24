import json
import threading

import httpx
import pytest

from conftest import load_tool_main

fanout_module = load_tool_main("fanout_tool")
fanout_main = fanout_module.main


@pytest.fixture(autouse=True)
def _reset_globals():
    # Mirrors how the sandbox injects PythonCodeToolConfig.configuration
    # values (and the crew-engine-injected `session_id`) as bare module
    # globals — see test_subflow_tool.py for the same pattern.
    names = [
        "graph_id",
        "graph_ids",
        "api_key",
        "api_base_url",
        "poll_timeout_s",
        "max_items",
        "max_workers",
        "session_id",
        "org_id",
    ]
    for name in names:
        if hasattr(fanout_module, name):
            delattr(fanout_module, name)
    yield
    for name in names:
        if hasattr(fanout_module, name):
            delattr(fanout_module, name)


_ORIGINAL_HTTPX_CLIENT = httpx.Client


def _mock_httpx_client(monkeypatch, handler):
    def _fake_client(**kwargs):
        return _ORIGINAL_HTTPX_CLIENT(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "Client", _fake_client)


def _configure(module, api_key="test-key", graph_id=None, graph_ids=None, **extra):
    module.api_key = api_key
    if graph_id is not None:
        module.graph_id = graph_id
    if graph_ids is not None:
        module.graph_ids = graph_ids
    for key, value in extra.items():
        setattr(module, key, value)


class TestFanoutToolParallel:
    def test_happy_path_runs_all_items_concurrently_and_returns_in_order(
        self, monkeypatch
    ):
        _configure(fanout_module, graph_id=42)
        fanout_module.session_id = 100

        # session ids are derived deterministically from each item's "n" so
        # the mock handler stays stateless/thread-safe under concurrency.
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["X-Api-Key"] == "test-key"

            if request.method == "GET" and request.url.path == "/api/sessions/100/":
                return httpx.Response(
                    200, json={"id": 100, "graph": 7, "parent_session": None}
                )

            if request.method == "POST" and request.url.path == "/api/run-session/":
                payload = json.loads(request.content)
                assert payload["graph_id"] == 42
                assert payload["parent_session_id"] == 100
                n = payload["variables"]["n"]
                return httpx.Response(201, json={"session_id": 1000 + n})

            if request.method == "GET" and request.url.path.startswith(
                "/api/sessions/1"
            ):
                sid = int(request.url.path.rstrip("/").rsplit("/", 1)[1])
                n = sid - 1000
                # Real API shape: top-level `variables` is the STATIC input
                # echo (never updated); the real output only lands in
                # `status_data.variables`. Kept deliberately different from
                # each other so this test actually exercises which one the
                # tool picks.
                return httpx.Response(
                    200,
                    json={
                        "id": sid,
                        "graph": 42,
                        "parent_session": 100,
                        "status": "end",
                        "variables": {"n": n},
                        "status_data": {"variables": {"result": n * 10}},
                    },
                )

            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        _mock_httpx_client(monkeypatch, handler)

        items = [{"n": 1}, {"n": 2}, {"n": 3}, {"n": 4}]
        result = fanout_main(mode="parallel", items=items)
        data = json.loads(result)

        assert data["mode"] == "parallel"
        assert data["results"] == [
            {"result": 10},
            {"result": 20},
            {"result": 30},
            {"result": 40},
        ]
        assert "truncated" not in data

    def test_returns_status_data_output_not_static_input_echo(self, monkeypatch):
        """Regression test (EST-3285): the top-level `variables` field on a
        session is a STATIC copy of the initial input, set once at session
        creation and never updated. The sub-flow's real, declared output
        (produced by the EndNode's output_map) only ever lands in
        `status_data.variables`, populated when the crew engine reports the
        session as finished. Against the pre-fix code (which read only
        `session_data["variables"]`), this test fails: it would return the
        echoed input `{"topic": "quantum computing"}` for every item instead
        of each item's real, distinct summary output."""
        _configure(fanout_module, graph_id=20)

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path == "/api/run-session/":
                payload = json.loads(request.content)
                topic = payload["variables"]["topic"]
                sid = {"quantum computing": 824, "black holes": 825}[topic]
                return httpx.Response(201, json={"session_id": sid})

            if request.method == "GET" and request.url.path in (
                "/api/sessions/824/",
                "/api/sessions/825/",
            ):
                sid = int(request.url.path.rstrip("/").rsplit("/", 1)[1])
                topic, summary = {
                    824: ("quantum computing", "Quantum computing uses qubits."),
                    825: ("black holes", "Black holes trap light via gravity."),
                }[sid]
                return httpx.Response(
                    200,
                    json={
                        "id": sid,
                        "graph": 20,
                        "parent_session": None,
                        "status": "end",
                        # Static input echo -- must NOT be returned.
                        "variables": {"topic": topic},
                        # Real EndNode-mapped output -- must be returned.
                        "status_data": {"variables": {"summary": summary}},
                    },
                )

            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        _mock_httpx_client(monkeypatch, handler)

        items = [{"topic": "quantum computing"}, {"topic": "black holes"}]
        result = fanout_main(mode="parallel", items=items)
        data = json.loads(result)

        assert data["results"] == [
            {"summary": "Quantum computing uses qubits."},
            {"summary": "Black holes trap light via gravity."},
        ]

    def test_one_failing_item_does_not_block_others(self, monkeypatch):
        _configure(fanout_module, graph_id=42)
        # No caller session_id -> recursion guard/linkage disabled but tool
        # still runs.

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path == "/api/run-session/":
                payload = json.loads(request.content)
                n = payload["variables"]["n"]
                return httpx.Response(201, json={"session_id": 2000 + n})

            if request.method == "GET" and request.url.path.startswith(
                "/api/sessions/2"
            ):
                sid = int(request.url.path.rstrip("/").rsplit("/", 1)[1])
                n = sid - 2000
                if n == 2:
                    return httpx.Response(
                        200,
                        json={
                            "id": sid,
                            "graph": 42,
                            "parent_session": None,
                            "status": "error",
                            "status_data": {"reason": "boom"},
                            "variables": {},
                        },
                    )
                return httpx.Response(
                    200,
                    json={
                        "id": sid,
                        "graph": 42,
                        "parent_session": None,
                        "status": "end",
                        "variables": {"result": n * 10},
                    },
                )

            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        _mock_httpx_client(monkeypatch, handler)

        items = [{"n": 1}, {"n": 2}, {"n": 3}]
        result = fanout_main(mode="parallel", items=items)
        data = json.loads(result)

        assert data["results"][0] == {"result": 10}
        assert "error" in data["results"][1]
        assert "boom" in data["results"][1]["error"]
        assert data["results"][2] == {"result": 30}

    def test_item_cap_truncation_is_announced(self, monkeypatch):
        _configure(fanout_module, graph_id=42, max_items=2)

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path == "/api/run-session/":
                payload = json.loads(request.content)
                n = payload["variables"]["n"]
                return httpx.Response(201, json={"session_id": 3000 + n})

            if request.method == "GET" and request.url.path.startswith(
                "/api/sessions/3"
            ):
                sid = int(request.url.path.rstrip("/").rsplit("/", 1)[1])
                n = sid - 3000
                return httpx.Response(
                    200,
                    json={
                        "id": sid,
                        "graph": 42,
                        "parent_session": None,
                        "status": "end",
                        "variables": {"result": n},
                    },
                )

            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        _mock_httpx_client(monkeypatch, handler)

        items = [{"n": 1}, {"n": 2}, {"n": 3}, {"n": 4}, {"n": 5}]
        result = fanout_main(mode="parallel", items=items)
        data = json.loads(result)

        assert data["truncated"] is True
        assert data["requested_items"] == 5
        assert data["used_items"] == 2
        assert len(data["results"]) == 2

    def test_missing_graph_id_returns_error(self):
        fanout_module.api_key = "test-key"

        result = fanout_main(mode="parallel", items=[{"n": 1}])

        assert result.startswith("Error:")
        assert "graph_id" in result

    def test_missing_api_key_returns_error(self):
        fanout_module.graph_id = 42

        result = fanout_main(mode="parallel", items=[{"n": 1}])

        assert result.startswith("Error:")
        assert "api_key" in result

    def test_missing_session_id_disables_guard_but_is_non_fatal(self, monkeypatch):
        _configure(fanout_module, graph_id=42)

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path == "/api/run-session/":
                payload = json.loads(request.content)
                assert "parent_session_id" not in payload
                return httpx.Response(201, json={"session_id": 4001})

            if request.method == "GET" and request.url.path == "/api/sessions/4001/":
                return httpx.Response(
                    200,
                    json={
                        "id": 4001,
                        "graph": 42,
                        "parent_session": None,
                        "status": "end",
                        "variables": {"result": "ok"},
                    },
                )

            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        _mock_httpx_client(monkeypatch, handler)

        result = fanout_main(mode="parallel", items=[{"n": 1}])
        data = json.loads(result)

        assert data["results"] == [{"result": "ok"}]

    def test_self_reference_recursion_guard_blocks_all_items(self, monkeypatch):
        _configure(fanout_module, graph_id=42)
        fanout_module.session_id = 100

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

        result = fanout_main(mode="parallel", items=[{"n": 1}, {"n": 2}])

        assert result.startswith("Error:")
        assert "recursion" in result

    def test_max_depth_guard(self, monkeypatch):
        _configure(fanout_module, graph_id=42)
        fanout_module.session_id = 1000

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

        result = fanout_main(mode="parallel", items=[{"n": 1}])

        assert result.startswith("Error:")
        assert "depth" in result or "deep" in result


class TestFanoutToolPipeline:
    def test_happy_path_threads_output_stage_to_stage(self, monkeypatch):
        _configure(fanout_module, graph_ids=[10, 20, 30])
        fanout_module.session_id = 100

        call_log = []
        lock = threading.Lock()

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET" and request.url.path == "/api/sessions/100/":
                return httpx.Response(
                    200, json={"id": 100, "graph": 7, "parent_session": None}
                )

            if request.method == "POST" and request.url.path == "/api/run-session/":
                payload = json.loads(request.content)
                with lock:
                    call_log.append(payload)
                gid = payload["graph_id"]
                sid = 9000 + gid
                return httpx.Response(201, json={"session_id": sid})

            if request.method == "GET" and request.url.path.startswith(
                "/api/sessions/9"
            ):
                sid = int(request.url.path.rstrip("/").rsplit("/", 1)[1])
                gid = sid - 9000
                # each stage's real output is the running "value"; the
                # top-level `variables` is deliberately kept as the STATIC
                # input echo instead, so this test proves the tool reads
                # `status_data.variables`, not `variables`.
                return httpx.Response(
                    200,
                    json={
                        "id": sid,
                        "graph": gid,
                        "parent_session": None,
                        "status": "end",
                        "variables": {"value": 1},
                        "status_data": {"variables": {"value": gid}},
                    },
                )

            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        _mock_httpx_client(monkeypatch, handler)

        result = fanout_main(mode="pipeline", input={"value": 1})
        data = json.loads(result)

        assert data["mode"] == "pipeline"
        assert data["final_output"] == {"value": 30}
        assert data["stage_outputs"] == [
            {"value": 10},
            {"value": 20},
            {"value": 30},
        ]

        # stage 1 receives the original input; stage 2 receives stage 1's
        # output; stage 3 receives stage 2's output; each stage's parent
        # session chains from the previous stage's session (or the caller
        # for stage 1).
        assert call_log[0]["variables"] == {"value": 1}
        assert call_log[0]["parent_session_id"] == 100
        assert call_log[1]["variables"] == {"value": 10}
        assert call_log[1]["parent_session_id"] == 9010
        assert call_log[2]["variables"] == {"value": 20}
        assert call_log[2]["parent_session_id"] == 9020

    def test_stage_failure_stops_the_chain(self, monkeypatch):
        _configure(fanout_module, graph_ids=[10, 20, 30])

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path == "/api/run-session/":
                payload = json.loads(request.content)
                gid = payload["graph_id"]
                return httpx.Response(201, json={"session_id": 9000 + gid})

            if request.method == "GET" and request.url.path.startswith(
                "/api/sessions/9"
            ):
                sid = int(request.url.path.rstrip("/").rsplit("/", 1)[1])
                gid = sid - 9000
                if gid == 20:
                    return httpx.Response(
                        200,
                        json={
                            "id": sid,
                            "graph": gid,
                            "parent_session": None,
                            "status": "error",
                            "status_data": {"reason": "stage 2 exploded"},
                            "variables": {},
                        },
                    )
                return httpx.Response(
                    200,
                    json={
                        "id": sid,
                        "graph": gid,
                        "parent_session": None,
                        "status": "end",
                        "variables": {"value": gid},
                    },
                )

            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        _mock_httpx_client(monkeypatch, handler)

        result = fanout_main(mode="pipeline", input={"value": 1})

        assert result.startswith("Error:")
        assert "stage 1" in result
        assert "stage 2 exploded" in result

    def test_missing_graph_ids_returns_error(self):
        fanout_module.api_key = "test-key"

        result = fanout_main(mode="pipeline", input={})

        assert result.startswith("Error:")
        assert "graph_ids" in result

    def test_missing_api_key_returns_error(self):
        fanout_module.graph_ids = [10, 20]

        result = fanout_main(mode="pipeline", input={})

        assert result.startswith("Error:")
        assert "api_key" in result

    def test_stage_cap_is_rejected(self):
        _configure(fanout_module, graph_ids=[1, 2, 3, 4], max_items=2)

        result = fanout_main(mode="pipeline", input={})

        assert result.startswith("Error:")
        assert "stage" in result

    def test_self_reference_recursion_guard_stops_chain(self, monkeypatch):
        _configure(fanout_module, graph_ids=[42])
        fanout_module.session_id = 100

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

        result = fanout_main(mode="pipeline", input={})

        assert result.startswith("Error:")
        assert "recursion" in result

    def test_max_depth_guard(self, monkeypatch):
        _configure(fanout_module, graph_ids=[42])
        fanout_module.session_id = 1000

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

        result = fanout_main(mode="pipeline", input={})

        assert result.startswith("Error:")
        assert "depth" in result or "deep" in result


class TestFanoutToolResilience:
    """Covers FIX B (EST-3285 QA report): 'server disconnected without
    sending a response' (httpx.RemoteProtocolError) and other transient
    connection errors must not abort an item outright -- see
    `_post_run_session_with_retry` / `_poll_until_terminal` in main.py."""

    def test_transient_poll_error_recovers_and_item_still_succeeds(self, monkeypatch):
        """A single transient RemoteProtocolError on a poll GET is retried
        (non-fatal) and the item succeeds once the next poll gets a normal
        response -- proves the poll loop no longer treats one dropped
        connection as a fatal error."""
        _configure(fanout_module, graph_id=42)
        monkeypatch.setattr(fanout_module.time, "sleep", lambda s: None)

        poll_calls = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path == "/api/run-session/":
                return httpx.Response(201, json={"session_id": 6001})

            if request.method == "GET" and request.url.path == "/api/sessions/6001/":
                poll_calls["count"] += 1
                if poll_calls["count"] == 1:
                    raise httpx.RemoteProtocolError(
                        "server disconnected without sending a response"
                    )
                return httpx.Response(
                    200,
                    json={
                        "id": 6001,
                        "graph": 42,
                        "parent_session": None,
                        "status": "end",
                        "variables": {"result": "recovered"},
                    },
                )

            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        _mock_httpx_client(monkeypatch, handler)

        result = fanout_main(mode="parallel", items=[{"n": 1}])
        data = json.loads(result)

        assert data["results"] == [{"result": "recovered"}]
        # First poll hit the transient error, second poll succeeded.
        assert poll_calls["count"] == 2

    def test_post_retries_transient_error_then_succeeds(self, monkeypatch):
        """The initial POST /run-session/ retries on a transient connection
        error and succeeds on a later attempt (proves FIX B item 2)."""
        _configure(fanout_module, graph_id=42)
        monkeypatch.setattr(fanout_module.time, "sleep", lambda s: None)

        post_calls = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path == "/api/run-session/":
                post_calls["count"] += 1
                if post_calls["count"] < 2:
                    raise httpx.ConnectError("connection refused")
                return httpx.Response(201, json={"session_id": 6002})

            if request.method == "GET" and request.url.path == "/api/sessions/6002/":
                return httpx.Response(
                    200,
                    json={
                        "id": 6002,
                        "graph": 42,
                        "parent_session": None,
                        "status": "end",
                        "variables": {"result": "ok"},
                    },
                )

            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        _mock_httpx_client(monkeypatch, handler)

        result = fanout_main(mode="parallel", items=[{"n": 1}])
        data = json.loads(result)

        assert data["results"] == [{"result": "ok"}]
        assert post_calls["count"] == 2

    def test_post_gives_up_after_exhausting_retries(self, monkeypatch):
        """A persistent transient error on the POST exhausts
        POST_MAX_ATTEMPTS and returns a distinct transient-error message,
        not a generic one."""
        _configure(fanout_module, graph_id=42)
        monkeypatch.setattr(fanout_module.time, "sleep", lambda s: None)

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path == "/api/run-session/":
                raise httpx.RemoteProtocolError(
                    "server disconnected without sending a response"
                )
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        _mock_httpx_client(monkeypatch, handler)

        result = fanout_main(mode="parallel", items=[{"n": 1}])
        data = json.loads(result)

        error = data["results"][0]["error"]
        assert "transient connection error" in error
        assert f"gave up after {fanout_module.POST_MAX_ATTEMPTS} attempt" in error

    def test_persistent_poll_disconnect_exceeds_cap_and_reports_transient_error(
        self, monkeypatch
    ):
        """A poll GET that NEVER recovers exhausts
        MAX_CONSECUTIVE_POLL_ERRORS and reports a clearly transient-error
        message -- distinguishable from a real sub-flow failure ('failed:')
        and from a plain timeout ('did not finish within Ns')."""
        _configure(fanout_module, graph_id=42)
        monkeypatch.setattr(fanout_module.time, "sleep", lambda s: None)

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path == "/api/run-session/":
                return httpx.Response(201, json={"session_id": 6003})

            if request.method == "GET" and request.url.path == "/api/sessions/6003/":
                raise httpx.RemoteProtocolError(
                    "server disconnected without sending a response"
                )

            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        _mock_httpx_client(monkeypatch, handler)

        result = fanout_main(mode="parallel", items=[{"n": 1}])
        data = json.loads(result)

        error = data["results"][0]["error"]
        assert "consecutive transient connection errors" in error
        assert "transient server disconnect" in error
        # Must not be mistaken for a real sub-flow failure or a plain timeout.
        assert "session ended with status" not in error
        assert "did not finish within" not in error

    def test_persistent_poll_disconnect_does_not_exceed_max_workers_pool(
        self, monkeypatch
    ):
        """Sanity check: multiple items each hitting persistent transient
        poll errors still resolve independently (one shared pooled client,
        no cross-item interference) and each gets its own clear transient
        error message."""
        _configure(fanout_module, graph_id=42, max_workers=2)
        monkeypatch.setattr(fanout_module.time, "sleep", lambda s: None)

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path == "/api/run-session/":
                payload = json.loads(request.content)
                n = payload["variables"]["n"]
                return httpx.Response(201, json={"session_id": 7000 + n})

            if request.method == "GET" and request.url.path.startswith(
                "/api/sessions/7"
            ):
                raise httpx.RemoteProtocolError(
                    "server disconnected without sending a response"
                )

            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        _mock_httpx_client(monkeypatch, handler)

        result = fanout_main(mode="parallel", items=[{"n": 1}, {"n": 2}])
        data = json.loads(result)

        for entry in data["results"]:
            assert "consecutive transient connection errors" in entry["error"]


class TestFanoutToolCommon:
    def test_invalid_mode_returns_error(self):
        fanout_module.api_key = "test-key"

        result = fanout_main(mode="bogus")

        assert result.startswith("Error:")
        assert "mode" in result

    def test_stray_config_kwargs_are_absorbed_and_globals_win(self, monkeypatch):
        """Regression test (EST-3285 smoke test): python_code.global_kwargs
        folds user_input config (graph_id/api_key/poll_timeout_s/etc.) into
        func_kwargs, so main() may also receive them as kwargs even though
        main()'s real signature is only (mode, items, input). The globals
        remain the source of truth; the stray kwargs must be swallowed by
        **kwargs without a TypeError."""
        _configure(fanout_module, api_key="real-key", graph_id=42)

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["X-Api-Key"] == "real-key"
            if request.method == "POST" and request.url.path == "/api/run-session/":
                payload = json.loads(request.content)
                assert payload["graph_id"] == 42
                return httpx.Response(201, json={"session_id": 5001})
            if request.method == "GET" and request.url.path == "/api/sessions/5001/":
                return httpx.Response(
                    200,
                    json={
                        "id": 5001,
                        "graph": 42,
                        "parent_session": None,
                        "status": "end",
                        "variables": {"result": "ok"},
                    },
                )
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        _mock_httpx_client(monkeypatch, handler)

        result = fanout_main(
            mode="parallel",
            items=[{"n": 1}],
            graph_id=999,
            api_key="stray-kwarg-key",
        )
        data = json.loads(result)

        assert data["results"] == [{"result": "ok"}]


class TestFanoutToolHeaders:
    """EST-3285: org_id (server-side resolved from Graph.org_id, injected by
    the crew engine) must be sent as X-Organization-Id so org-scoped API
    endpoints (e.g. GET /sessions/<id>/) don't 400 with org_context_required."""

    def test_headers_includes_org_header_when_org_id_injected(self):
        fanout_module.org_id = 42

        headers = fanout_module._headers("test-key")

        assert headers["X-Organization-Id"] == "42"
        assert headers["X-Api-Key"] == "test-key"

    def test_headers_omits_org_header_when_org_id_absent(self):
        headers = fanout_module._headers("test-key")

        assert "X-Organization-Id" not in headers
        assert headers["X-Api-Key"] == "test-key"
