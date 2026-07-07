import httpx
import pytest

from conftest import load_tool_main

wfd_module = load_tool_main("wait_for_decision_tool")
wfd_main = wfd_module.main


@pytest.fixture(autouse=True)
def _reset_globals():
    names = ["api_key", "api_base_url", "poll_timeout_s", "session_id"]
    for name in names:
        if hasattr(wfd_module, name):
            delattr(wfd_module, name)
    yield
    for name in names:
        if hasattr(wfd_module, name):
            delattr(wfd_module, name)


_ORIGINAL_HTTPX_CLIENT = httpx.Client


def _mock_httpx_client(monkeypatch, handler):
    def _fake_client(**kwargs):
        return _ORIGINAL_HTTPX_CLIENT(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "Client", _fake_client)


def _configure(module, api_key="test-key", session_id=100, poll_timeout_s=None):
    module.api_key = api_key
    module.session_id = session_id
    if poll_timeout_s is not None:
        module.poll_timeout_s = poll_timeout_s


class TestWaitForDecisionTool:
    def test_happy_path_opens_polls_and_returns_option_answer(self, monkeypatch):
        _configure(wfd_module)
        calls = {"gets": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["X-Api-Key"] == "test-key"

            if (
                request.method == "POST"
                and request.url.path == "/api/sessions/100/decisions/open/"
            ):
                import json as _json

                payload = _json.loads(request.content)
                assert payload["question"] == "Proceed?"
                assert payload["options"] == ["yes", "no"]
                assert payload["allow_free_text"] is True
                return httpx.Response(
                    201, json={"decision_id": "dec-1", "status": "wait_for_user"}
                )

            if request.method == "GET" and request.url.path == "/api/sessions/100/":
                calls["gets"] += 1
                if calls["gets"] == 1:
                    return httpx.Response(
                        200,
                        json={
                            "id": 100,
                            "status": "wait_for_user",
                            "status_data": {
                                "decision": {"decision_id": "dec-1", "answer": None}
                            },
                        },
                    )
                return httpx.Response(
                    200,
                    json={
                        "id": 100,
                        "status": "run",
                        "status_data": {
                            "decision": {
                                "decision_id": "dec-1",
                                "answer": {"option_index": 0, "free_text": None},
                            }
                        },
                    },
                )

            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        _mock_httpx_client(monkeypatch, handler)
        monkeypatch.setattr(wfd_module.time, "sleep", lambda *_a, **_k: None)

        result = wfd_main(question="Proceed?", options=["yes", "no"])

        assert "selected option 0" in result
        assert "'yes'" in result
        assert calls["gets"] == 2

    def test_happy_path_returns_free_text_answer(self, monkeypatch):
        _configure(wfd_module)

        def handler(request: httpx.Request) -> httpx.Response:
            if (
                request.method == "POST"
                and request.url.path == "/api/sessions/100/decisions/open/"
            ):
                return httpx.Response(201, json={"decision_id": "dec-1"})

            if request.method == "GET" and request.url.path == "/api/sessions/100/":
                return httpx.Response(
                    200,
                    json={
                        "status_data": {
                            "decision": {
                                "decision_id": "dec-1",
                                "answer": {
                                    "option_index": None,
                                    "free_text": "actually wait",
                                },
                            }
                        }
                    },
                )
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        _mock_httpx_client(monkeypatch, handler)

        result = wfd_main(question="Proceed?", options=["yes", "no"])

        assert "actually wait" in result

    def test_missing_session_id_returns_error(self):
        wfd_module.api_key = "test-key"

        result = wfd_main(question="Proceed?", options=["yes", "no"])

        assert result.startswith("Error:")
        assert "session_id" in result

    def test_missing_api_key_returns_error(self):
        wfd_module.session_id = 100

        result = wfd_main(question="Proceed?", options=["yes", "no"])

        assert result.startswith("Error:")
        assert "api_key" in result

    def test_missing_question_returns_error(self):
        _configure(wfd_module)

        result = wfd_main(question="", options=["yes", "no"])

        assert result.startswith("Error:")
        assert "question" in result

    def test_too_few_options_returns_error(self):
        _configure(wfd_module)

        result = wfd_main(question="Proceed?", options=["only-one"])

        assert result.startswith("Error:")
        assert "options" in result

    def test_too_many_options_returns_error(self):
        _configure(wfd_module)

        result = wfd_main(question="Proceed?", options=["a", "b", "c", "d", "e"])

        assert result.startswith("Error:")

    def test_stray_config_kwargs_are_absorbed_and_globals_win(self, monkeypatch):
        """Regression test (EST-3285 smoke test): python_code.global_kwargs
        folds user_input config (api_key/poll_timeout_s) into func_kwargs,
        so main() may also receive them as kwargs even though main()'s real
        signature has no such params. The globals remain the source of
        truth (the mock handler asserts the real 'test-key' header below);
        the stray kwargs must be swallowed by **kwargs without a TypeError."""
        _configure(wfd_module)

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["X-Api-Key"] == "test-key"

            if (
                request.method == "POST"
                and request.url.path == "/api/sessions/100/decisions/open/"
            ):
                return httpx.Response(201, json={"decision_id": "dec-1"})

            if request.method == "GET" and request.url.path == "/api/sessions/100/":
                return httpx.Response(
                    200,
                    json={
                        "status_data": {
                            "decision": {
                                "decision_id": "dec-1",
                                "answer": {"option_index": 0, "free_text": None},
                            }
                        }
                    },
                )
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        _mock_httpx_client(monkeypatch, handler)

        result = wfd_main(
            question="Proceed?",
            options=["yes", "no"],
            api_key="stray-kwarg-key",
        )

        assert "selected option 0" in result

    def test_open_call_failure_returns_error(self, monkeypatch):
        _configure(wfd_module)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        _mock_httpx_client(monkeypatch, handler)

        result = wfd_main(question="Proceed?", options=["yes", "no"])

        assert result.startswith("Error:")
        assert "500" in result

    def test_poll_timeout_cancels_and_returns_readable_error(self, monkeypatch):
        _configure(wfd_module, poll_timeout_s=0)
        cancel_calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            if (
                request.method == "POST"
                and request.url.path == "/api/sessions/100/decisions/open/"
            ):
                return httpx.Response(201, json={"decision_id": "dec-1"})

            if request.method == "GET" and request.url.path == "/api/sessions/100/":
                return httpx.Response(
                    200,
                    json={
                        "status_data": {
                            "decision": {"decision_id": "dec-1", "answer": None}
                        }
                    },
                )

            if (
                request.method == "POST"
                and request.url.path == "/api/sessions/100/decisions/cancel/"
            ):
                cancel_calls.append(request)
                return httpx.Response(200, json={"cancelled": True, "status": "run"})

            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        _mock_httpx_client(monkeypatch, handler)

        result = wfd_main(question="Proceed?", options=["yes", "no"])

        assert result.startswith("Error:")
        assert "no decision received within 0s" in result
        assert "resumed" in result
        assert len(cancel_calls) == 1
