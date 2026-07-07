import httpx
import pytest

from conftest import load_tool_main

web_fetch_module = load_tool_main("web_fetch_tool")
web_fetch_main = web_fetch_module.main

HTML_PAGE = """
<html>
<head><title>Example Domain Page</title></head>
<body>
<h1>Example Domain Page</h1>
<p>This domain is for use in illustrative examples in documents.</p>
</body>
</html>
"""


_ORIGINAL_HTTPX_CLIENT = httpx.Client


def _mock_httpx_client(monkeypatch, handler):
    def _fake_client(**kwargs):
        return _ORIGINAL_HTTPX_CLIENT(
            transport=httpx.MockTransport(handler), follow_redirects=False
        )

    monkeypatch.setattr(httpx, "Client", _fake_client)


class TestWebFetchTool:
    def test_markdown_extraction_happy_path(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, text=HTML_PAGE, headers={"content-type": "text/html"}
            )

        _mock_httpx_client(monkeypatch, handler)

        result = web_fetch_main(url="https://example.com/")

        assert "Example Domain Page" in result

    def test_http_upgraded_to_https(self, monkeypatch):
        requested_urls = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested_urls.append(str(request.url))
            return httpx.Response(
                200, text=HTML_PAGE, headers={"content-type": "text/html"}
            )

        _mock_httpx_client(monkeypatch, handler)

        web_fetch_main(url="http://example.com/")

        assert requested_urls[0].startswith("https://")

    def test_ssrf_refuses_link_local_metadata_address(self):
        result = web_fetch_main(url="http://169.254.169.254/")

        assert result.startswith("Error:")
        assert "SSRF" in result

    def test_ssrf_refuses_loopback_address(self):
        result = web_fetch_main(url="http://127.0.0.1/")

        assert result.startswith("Error:")
        assert "SSRF" in result

    def test_cross_host_redirect_returns_message_without_following(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                302, headers={"location": "https://other-host.com/target"}
            )

        _mock_httpx_client(monkeypatch, handler)

        result = web_fetch_main(url="https://example.com/")

        assert result == "Redirects to https://other-host.com/target — call again with that URL"

    def test_same_host_redirect_is_followed(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/start":
                return httpx.Response(
                    301, headers={"location": "https://example.com/final"}
                )
            return httpx.Response(
                200, text=HTML_PAGE, headers={"content-type": "text/html"}
            )

        _mock_httpx_client(monkeypatch, handler)

        result = web_fetch_main(url="https://example.com/start")

        assert "Example Domain Page" in result

    def test_binary_content_type_returns_error(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=b"\x89PNG\r\n\x1a\n",
                headers={"content-type": "image/png"},
            )

        _mock_httpx_client(monkeypatch, handler)

        result = web_fetch_main(url="https://example.com/logo.png")

        assert result.startswith("Error:")
        assert "image/png" in result

    def test_oversize_download_is_announced(self, monkeypatch):
        oversized_html = "<html><body>" + ("x" * (6 * 1024 * 1024)) + "</body></html>"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, text=oversized_html, headers={"content-type": "text/html"}
            )

        _mock_httpx_client(monkeypatch, handler)

        result = web_fetch_main(url="https://example.com/big")

        assert "truncated" in result
        assert "MB cap" in result

    def test_missing_url_returns_error(self):
        result = web_fetch_main(url="")

        assert result.startswith("Error:")
        assert "url" in result

    def test_invalid_scheme_returns_error(self):
        result = web_fetch_main(url="ftp://example.com/file")

        assert result.startswith("Error:")
        assert "scheme" in result

    def test_ssrf_guard_returns_failure_tuple_for_malformed_url(self):
        """`_ssrf_guard` must not raise on a URL httpx can't parse (e.g. an
        invalid port) -- it should fail closed with the standard (False, msg)
        tuple, same defensive pattern as notification_tool's `_ssrf_guard`."""
        ok, err = web_fetch_module._ssrf_guard("http://example.com:abc/")

        assert ok is False
        assert err.startswith("Error: invalid URL")
