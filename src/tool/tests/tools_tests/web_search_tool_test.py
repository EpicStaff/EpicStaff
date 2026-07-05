import httpx
import pytest

from custom_tools import WebSearchTool
from tests.tools_tests.new_tools_fixtures import web_search_tool, web_search_tool_no_key


def _make_organic(n: int, host: str = "example.com") -> list[dict]:
    return [
        {
            "title": f"Result {i}",
            "link": f"https://{host}/page-{i}",
            "snippet": f"Snippet content {i}",
        }
        for i in range(n)
    ]


def _mock_client(monkeypatch, tool: WebSearchTool, handler):
    def _build_client(self):
        return httpx.Client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(WebSearchTool, "_build_client", _build_client)


class TestWebSearchTool:
    def test_happy_path_formatting(self, monkeypatch, web_search_tool: WebSearchTool):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["X-API-KEY"] == "test-serper-key"
            return httpx.Response(200, json={"organic": _make_organic(2)})

        _mock_client(monkeypatch, web_search_tool, handler)

        result = web_search_tool._run(query="python testing")

        lines = result.splitlines()
        assert lines[0] == "1. Result 0"
        assert lines[1] == "   https://example.com/page-0"
        assert lines[2] == "   Snippet content 0"
        assert lines[3] == "2. Result 1"

    def test_allowed_domains_filters_results(
        self, monkeypatch, web_search_tool: WebSearchTool
    ):
        def handler(request: httpx.Request) -> httpx.Response:
            organic = _make_organic(2, host="github.com") + _make_organic(
                2, host="stackoverflow.com"
            )
            return httpx.Response(200, json={"organic": organic})

        _mock_client(monkeypatch, web_search_tool, handler)

        result = web_search_tool._run(
            query="python testing", allowed_domains=["github.com"]
        )

        assert "github.com" in result
        assert "stackoverflow.com" not in result

    def test_blocked_domains_excludes_results(
        self, monkeypatch, web_search_tool: WebSearchTool
    ):
        def handler(request: httpx.Request) -> httpx.Response:
            organic = _make_organic(2, host="github.com") + _make_organic(
                2, host="spammy.com"
            )
            return httpx.Response(200, json={"organic": organic})

        _mock_client(monkeypatch, web_search_tool, handler)

        result = web_search_tool._run(
            query="python testing", blocked_domains=["spammy.com"]
        )

        assert "github.com" in result
        assert "spammy.com" not in result

    def test_missing_api_key_returns_error(
        self, web_search_tool_no_key: WebSearchTool
    ):
        result = web_search_tool_no_key._run(query="python testing")

        assert result.startswith("Error:")
        assert "api_key" in result

    def test_provider_error_status_returns_readable_string(
        self, monkeypatch, web_search_tool: WebSearchTool
    ):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, text="Forbidden: invalid API key")

        _mock_client(monkeypatch, web_search_tool, handler)

        result = web_search_tool._run(query="python testing")

        assert result.startswith("Error:")
        assert "403" in result

    def test_network_error_returns_readable_string(
        self, monkeypatch, web_search_tool: WebSearchTool
    ):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        _mock_client(monkeypatch, web_search_tool, handler)

        result = web_search_tool._run(query="python testing")

        assert result.startswith("Error:")

    def test_short_query_returns_error(self, web_search_tool: WebSearchTool):
        result = web_search_tool._run(query="a")

        assert result.startswith("Error:")
        assert "2 characters" in result

    def test_snippet_truncated_and_announced(
        self, monkeypatch, web_search_tool: WebSearchTool
    ):
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

        _mock_client(monkeypatch, web_search_tool, handler)

        result = web_search_tool._run(query="python testing", max_results=1)

        body_line = result.splitlines()[2]
        assert len(body_line) < len(long_snippet)
        assert body_line.endswith("…")

    def test_truncation_of_result_count_is_announced(
        self, monkeypatch, web_search_tool: WebSearchTool
    ):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"organic": _make_organic(5)})

        _mock_client(monkeypatch, web_search_tool, handler)

        result = web_search_tool._run(query="python testing", max_results=2)

        assert "showing 2 of 5 results" in result
