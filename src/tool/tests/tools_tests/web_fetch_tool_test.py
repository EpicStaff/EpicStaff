import httpx
import pytest

from custom_tools import WebFetchTool
from custom_tools.web_fetch_tool import _MARKDOWN_CACHE
from tests.tools_tests.new_tools_fixtures import web_fetch_tool, web_fetch_tool_with_llm

HTML_PAGE = """
<html>
<head><title>Example Domain Page</title></head>
<body>
<h1>Example Domain Page</h1>
<p>This domain is for use in illustrative examples in documents.</p>
</body>
</html>
"""


@pytest.fixture(autouse=True)
def _clear_cache():
    _MARKDOWN_CACHE.clear()
    yield
    _MARKDOWN_CACHE.clear()


def _mock_client(monkeypatch, handler):
    def _build_client(self):
        return httpx.Client(
            transport=httpx.MockTransport(handler), follow_redirects=False
        )

    monkeypatch.setattr(WebFetchTool, "_build_client", _build_client)


class TestWebFetchTool:
    def test_markdown_extraction_happy_path(
        self, monkeypatch, web_fetch_tool: WebFetchTool
    ):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, text=HTML_PAGE, headers={"content-type": "text/html"}
            )

        _mock_client(monkeypatch, handler)

        result = web_fetch_tool._run(url="https://example.com/")

        assert "Example Domain Page" in result

    def test_http_upgraded_to_https(self, monkeypatch, web_fetch_tool: WebFetchTool):
        requested_urls = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested_urls.append(str(request.url))
            return httpx.Response(
                200, text=HTML_PAGE, headers={"content-type": "text/html"}
            )

        _mock_client(monkeypatch, handler)

        web_fetch_tool._run(url="http://example.com/")

        assert requested_urls[0].startswith("https://")

    def test_ssrf_refuses_link_local_metadata_address(
        self, web_fetch_tool: WebFetchTool
    ):
        result = web_fetch_tool._run(url="http://169.254.169.254/")

        assert result.startswith("Error:")
        assert "SSRF" in result

    def test_ssrf_refuses_loopback_address(self, web_fetch_tool: WebFetchTool):
        result = web_fetch_tool._run(url="http://127.0.0.1/")

        assert result.startswith("Error:")
        assert "SSRF" in result

    def test_cross_host_redirect_returns_message_without_following(
        self, monkeypatch, web_fetch_tool: WebFetchTool
    ):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                302, headers={"location": "https://other-host.com/target"}
            )

        _mock_client(monkeypatch, handler)

        result = web_fetch_tool._run(url="https://example.com/")

        assert result == "Redirects to https://other-host.com/target — call again with that URL"

    def test_same_host_redirect_is_followed(
        self, monkeypatch, web_fetch_tool: WebFetchTool
    ):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/start":
                return httpx.Response(
                    301, headers={"location": "https://example.com/final"}
                )
            return httpx.Response(
                200, text=HTML_PAGE, headers={"content-type": "text/html"}
            )

        _mock_client(monkeypatch, handler)

        result = web_fetch_tool._run(url="https://example.com/start")

        assert "Example Domain Page" in result

    def test_binary_content_type_returns_error(
        self, monkeypatch, web_fetch_tool: WebFetchTool
    ):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=b"\x89PNG\r\n\x1a\n",
                headers={"content-type": "image/png"},
            )

        _mock_client(monkeypatch, handler)

        result = web_fetch_tool._run(url="https://example.com/logo.png")

        assert result.startswith("Error:")
        assert "image/png" in result

    def test_cache_hit_within_ttl_does_not_hit_network(
        self, monkeypatch, web_fetch_tool: WebFetchTool
    ):
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            return httpx.Response(
                200, text=HTML_PAGE, headers={"content-type": "text/html"}
            )

        _mock_client(monkeypatch, handler)

        first = web_fetch_tool._run(url="https://example.com/")
        second = web_fetch_tool._run(url="https://example.com/")

        assert first == second
        assert call_count["n"] == 1

    def test_oversize_download_is_announced(
        self, monkeypatch, web_fetch_tool: WebFetchTool
    ):
        oversized_html = "<html><body>" + ("x" * (6 * 1024 * 1024)) + "</body></html>"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, text=oversized_html, headers={"content-type": "text/html"}
            )

        _mock_client(monkeypatch, handler)

        result = web_fetch_tool._run(url="https://example.com/big")

        assert "truncated" in result
        assert "MB cap" in result

    def test_prompt_calls_llm_and_returns_answer(
        self, monkeypatch, web_fetch_tool_with_llm: WebFetchTool
    ):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, text=HTML_PAGE, headers={"content-type": "text/html"}
            )

        _mock_client(monkeypatch, handler)

        captured = {}

        class _Message:
            content = "The page is about example domains."

        class _Choice:
            message = _Message()

        class _Completion:
            choices = [_Choice()]

        def fake_completion(**kwargs):
            captured.update(kwargs)
            return _Completion()

        monkeypatch.setattr(
            "custom_tools.web_fetch_tool.litellm.completion", fake_completion
        )

        result = web_fetch_tool_with_llm._run(
            url="https://example.com/", prompt="What is this page about?"
        )

        assert result == "The page is about example domains."
        assert captured["model"] == "gpt-4o-mini"
        assert "What is this page about?" in captured["messages"][1]["content"]

    def test_prompt_without_llm_config_returns_error(
        self, monkeypatch, web_fetch_tool: WebFetchTool
    ):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, text=HTML_PAGE, headers={"content-type": "text/html"}
            )

        _mock_client(monkeypatch, handler)

        result = web_fetch_tool._run(
            url="https://example.com/", prompt="What is this page about?"
        )

        assert result.startswith("Error:")
        assert "llm_config" in result
