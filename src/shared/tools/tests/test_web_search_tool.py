import httpx
import pytest

from conftest import load_tool_main

web_search_module = load_tool_main("web_search_tool")
web_search_main = web_search_module.main


def _make_organic(n: int, host: str = "example.com") -> list[dict]:
    return [
        {
            "title": f"Result {i}",
            "link": f"https://{host}/page-{i}",
            "snippet": f"Snippet content {i}",
        }
        for i in range(n)
    ]


@pytest.fixture(autouse=True)
def _reset_api_key():
    # Mirrors how the sandbox injects PythonCodeToolConfig.configuration
    # values as bare module globals (see wrap_code() in
    # sandbox/dynamic_venv_executor_chain.py) — set/clear `api_key` directly
    # on the loaded module instead of passing it as a function argument.
    if hasattr(web_search_module, "api_key"):
        delattr(web_search_module, "api_key")
    yield
    if hasattr(web_search_module, "api_key"):
        delattr(web_search_module, "api_key")


_ORIGINAL_HTTPX_CLIENT = httpx.Client


def _mock_httpx_client(monkeypatch, handler):
    def _fake_client(**kwargs):
        return _ORIGINAL_HTTPX_CLIENT(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "Client", _fake_client)


class TestWebSearchTool:
    def test_happy_path_formatting(self, monkeypatch):
        web_search_module.api_key = "test-serper-key"

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["X-API-KEY"] == "test-serper-key"
            return httpx.Response(200, json={"organic": _make_organic(2)})

        _mock_httpx_client(monkeypatch, handler)

        result = web_search_main(query="python testing")

        lines = result.splitlines()
        assert lines[0] == "1. Result 0"
        assert lines[1] == "   https://example.com/page-0"
        assert lines[2] == "   Snippet content 0"
        assert lines[3] == "2. Result 1"

    def test_allowed_domains_filters_results(self, monkeypatch):
        web_search_module.api_key = "test-serper-key"

        def handler(request: httpx.Request) -> httpx.Response:
            organic = _make_organic(2, host="github.com") + _make_organic(
                2, host="stackoverflow.com"
            )
            return httpx.Response(200, json={"organic": organic})

        _mock_httpx_client(monkeypatch, handler)

        result = web_search_main(query="python testing", allowed_domains=["github.com"])

        assert "github.com" in result
        assert "stackoverflow.com" not in result

    def test_blocked_domains_excludes_results(self, monkeypatch):
        web_search_module.api_key = "test-serper-key"

        def handler(request: httpx.Request) -> httpx.Response:
            organic = _make_organic(2, host="github.com") + _make_organic(
                2, host="spammy.com"
            )
            return httpx.Response(200, json={"organic": organic})

        _mock_httpx_client(monkeypatch, handler)

        result = web_search_main(query="python testing", blocked_domains=["spammy.com"])

        assert "github.com" in result
        assert "spammy.com" not in result

    def test_api_key_passed_as_stray_kwarg_is_absorbed_and_global_wins(self, monkeypatch):
        """Regression test (smoke test): python_code.global_kwargs
        folds user_input config (api_key) into func_kwargs, so main() may
        also receive it as a kwarg. The global remains the source of
        truth; the stray kwarg must be swallowed by **kwargs without a
        TypeError."""
        web_search_module.api_key = "real-serper-key"

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["X-API-KEY"] == "real-serper-key"
            return httpx.Response(200, json={"organic": _make_organic(1)})

        _mock_httpx_client(monkeypatch, handler)

        result = web_search_main(query="python testing", api_key="stray-kwarg-key")

        assert not result.startswith("Error")

    def test_missing_api_key_returns_error(self):
        result = web_search_main(query="python testing")

        assert result.startswith("Error:")
        assert "api_key" in result

    def test_provider_error_status_returns_readable_string(self, monkeypatch):
        web_search_module.api_key = "test-serper-key"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, text="Forbidden: invalid API key")

        _mock_httpx_client(monkeypatch, handler)

        result = web_search_main(query="python testing")

        assert result.startswith("Error:")
        assert "403" in result

    def test_network_error_returns_readable_string(self, monkeypatch):
        web_search_module.api_key = "test-serper-key"

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        _mock_httpx_client(monkeypatch, handler)

        result = web_search_main(query="python testing")

        assert result.startswith("Error:")

    def test_short_query_returns_error(self):
        web_search_module.api_key = "test-serper-key"

        result = web_search_main(query="a")

        assert result.startswith("Error:")
        assert "2 characters" in result

    def test_snippet_truncated_and_announced(self, monkeypatch):
        web_search_module.api_key = "test-serper-key"
        long_snippet = "x" * 500

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "organic": [
                        {
                            "title": "Long result",
                            "link": "https://example.com/long",
                            "snippet": long_snippet,
                        }
                    ]
                },
            )

        _mock_httpx_client(monkeypatch, handler)

        result = web_search_main(query="python testing", max_results=1)

        body_line = result.splitlines()[2]
        assert len(body_line) < len(long_snippet)
        assert body_line.endswith("…")

    def test_truncation_of_result_count_is_announced(self, monkeypatch):
        web_search_module.api_key = "test-serper-key"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"organic": _make_organic(5)})

        _mock_httpx_client(monkeypatch, handler)

        result = web_search_main(query="python testing", max_results=2)

        assert "showing 2 of 5 results" in result
