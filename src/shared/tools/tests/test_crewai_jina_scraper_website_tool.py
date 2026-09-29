from conftest import FakeResponse, load_tool_main, make_fake_requests_get

jina_module = load_tool_main("crewai_jina_scraper_website_tool")
jina_main = jina_module.main


class TestJinaScraperWebsiteToolSsrf:
    def test_ssrf_refuses_loopback_address(self):
        result = jina_main(website_url="http://127.0.0.1/", api_key="test-key")

        assert result.startswith("Error:")
        assert "SSRF" in result

    def test_ssrf_refuses_link_local_metadata_address(self):
        result = jina_main(website_url="http://169.254.169.254/", api_key="test-key")

        assert result.startswith("Error:")
        assert "SSRF" in result

    def test_ssrf_refuses_invalid_scheme(self):
        result = jina_main(website_url="ftp://example.com/file", api_key="test-key")

        assert result.startswith("Error:")
        assert "scheme" in result

    def test_ssrf_guard_validates_user_url_not_jina_proxy_host(self):
        """The guard must check `website_url` (the agent-supplied target)
        rather than the `https://r.jina.ai/{website_url}` proxy URL that is
        actually requested. r.jina.ai always resolves to a public host, so
        guarding the proxy URL would never refuse anything and the SSRF
        protection would be a no-op."""
        ok, err = jina_module._ssrf_guard("http://127.0.0.1/internal")

        assert ok is False
        assert "SSRF" in err


class TestJinaScraperWebsiteToolRedirects:
    """The tool always fetches `https://r.jina.ai/{website_url}`, so from
    `_guarded_get`'s point of view the "original host" is `r.jina.ai`, not
    the agent-supplied target -- these tests exercise redirect handling on
    that proxy fetch itself (guarding `website_url` is covered above)."""

    def test_redirect_to_loopback_is_refused(self, monkeypatch):
        website_url = "http://example.com/page"
        proxy_url = f"https://r.jina.ai/{website_url}"
        responses = {
            proxy_url: FakeResponse(
                status_code=302, headers={"location": "http://127.0.0.1/"}
            ),
        }
        monkeypatch.setattr(
            jina_module.requests, "get", make_fake_requests_get(responses)
        )

        result = jina_main(website_url=website_url, api_key="test-key")

        assert "Redirects to" in result
        assert "http://127.0.0.1/" in result

    def test_same_host_redirect_is_followed(self, monkeypatch):
        website_url = "http://example.com/page"
        proxy_url = f"https://r.jina.ai/{website_url}"
        final_url = "https://r.jina.ai/other-path"
        responses = {
            proxy_url: FakeResponse(status_code=301, headers={"location": final_url}),
            final_url: FakeResponse(status_code=200, text="markdown content"),
        }
        monkeypatch.setattr(
            jina_module.requests, "get", make_fake_requests_get(responses)
        )

        result = jina_main(website_url=website_url, api_key="test-key")

        assert result == "markdown content"

    def test_cross_host_redirect_is_refused(self, monkeypatch):
        website_url = "http://example.com/page"
        proxy_url = f"https://r.jina.ai/{website_url}"
        target = "http://evil.example.net/"
        responses = {
            proxy_url: FakeResponse(status_code=302, headers={"location": target}),
        }
        monkeypatch.setattr(
            jina_module.requests, "get", make_fake_requests_get(responses)
        )

        result = jina_main(website_url=website_url, api_key="test-key")

        assert result == f"Redirects to {target} — call again with that URL"

    def test_redirect_loop_hits_hop_cap(self, monkeypatch):
        website_url = "http://example.com/page"
        proxy_url = f"https://r.jina.ai/{website_url}"
        responses = {
            proxy_url: FakeResponse(status_code=302, headers={"location": proxy_url}),
        }
        monkeypatch.setattr(
            jina_module.requests, "get", make_fake_requests_get(responses)
        )

        result = jina_main(website_url=website_url, api_key="test-key")

        assert "exceeded max redirects" in result
        assert str(jina_module.MAX_REDIRECTS) in result
