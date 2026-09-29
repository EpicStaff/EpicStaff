from conftest import FakeResponse, load_tool_main, make_fake_requests_get

website_search_module = load_tool_main("crewai_website_search_tool")
website_search_main = website_search_module.main

HTML_BODY = "<html><body><p>needle in a haystack</p></body></html>"


class TestWebsiteSearchToolSsrf:
    def test_ssrf_refuses_loopback_address(self):
        result = website_search_main(search_query="test", website="http://127.0.0.1/")

        assert result.startswith("Error:")
        assert "SSRF" in result

    def test_ssrf_refuses_link_local_metadata_address(self):
        result = website_search_main(
            search_query="test", website="http://169.254.169.254/"
        )

        assert result.startswith("Error:")
        assert "SSRF" in result

    def test_ssrf_refuses_invalid_scheme(self):
        result = website_search_main(search_query="test", website="ftp://example.com/file")

        assert result.startswith("Error:")
        assert "scheme" in result


class TestWebsiteSearchToolRedirects:
    def test_redirect_to_loopback_is_refused(self, monkeypatch):
        """The bug: a public URL that 302-redirects to a loopback address
        must not be followed unguarded."""
        url = "http://example.com/page"
        responses = {
            url: FakeResponse(
                status_code=302, headers={"location": "http://127.0.0.1/"}
            ),
        }
        monkeypatch.setattr(
            website_search_module.requests, "get", make_fake_requests_get(responses)
        )

        result = website_search_main(search_query="needle", website=url)

        assert "Redirects to" in result
        assert "http://127.0.0.1/" in result

    def test_same_host_redirect_is_followed(self, monkeypatch):
        url = "http://example.com/page"
        final_url = "https://example.com/page"
        responses = {
            url: FakeResponse(status_code=301, headers={"location": final_url}),
            final_url: FakeResponse(status_code=200, text=HTML_BODY),
        }
        monkeypatch.setattr(
            website_search_module.requests, "get", make_fake_requests_get(responses)
        )

        result = website_search_main(search_query="needle", website=url)

        assert "needle in a haystack" in result

    def test_cross_host_redirect_is_refused(self, monkeypatch):
        url = "http://example.com/page"
        target = "http://evil.example.net/"
        responses = {
            url: FakeResponse(status_code=302, headers={"location": target}),
        }
        monkeypatch.setattr(
            website_search_module.requests, "get", make_fake_requests_get(responses)
        )

        result = website_search_main(search_query="needle", website=url)

        assert result == f"Redirects to {target} — call again with that URL"

    def test_redirect_loop_hits_hop_cap(self, monkeypatch):
        url = "http://example.com/page"
        responses = {
            url: FakeResponse(status_code=302, headers={"location": url}),
        }
        monkeypatch.setattr(
            website_search_module.requests, "get", make_fake_requests_get(responses)
        )

        result = website_search_main(search_query="needle", website=url)

        assert "exceeded max redirects" in result
        assert str(website_search_module.MAX_REDIRECTS) in result
