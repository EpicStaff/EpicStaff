from conftest import FakeResponse, load_tool_main, make_fake_requests_get

scrape_element_module = load_tool_main("crewai_scrape_element_from_website_tool")
scrape_element_main = scrape_element_module.main

HTML_BODY = "<html><body><p>Hello</p></body></html>"


class TestScrapeElementFromWebsiteToolSsrf:
    def test_ssrf_refuses_loopback_address(self):
        result = scrape_element_main(website_url="http://127.0.0.1/", css_element="p")

        assert result.startswith("Error:")
        assert "SSRF" in result

    def test_ssrf_refuses_link_local_metadata_address(self):
        result = scrape_element_main(
            website_url="http://169.254.169.254/", css_element="p"
        )

        assert result.startswith("Error:")
        assert "SSRF" in result

    def test_ssrf_refuses_invalid_scheme(self):
        result = scrape_element_main(website_url="ftp://example.com/file", css_element="p")

        assert result.startswith("Error:")
        assert "scheme" in result


class TestScrapeElementFromWebsiteToolRedirects:
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
            scrape_element_module.requests, "get", make_fake_requests_get(responses)
        )

        result = scrape_element_main(website_url=url, css_element="p")

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
            scrape_element_module.requests, "get", make_fake_requests_get(responses)
        )

        result = scrape_element_main(website_url=url, css_element="p")

        assert result == "Hello"

    def test_cross_host_redirect_is_refused(self, monkeypatch):
        url = "http://example.com/page"
        target = "http://evil.example.net/"
        responses = {
            url: FakeResponse(status_code=302, headers={"location": target}),
        }
        monkeypatch.setattr(
            scrape_element_module.requests, "get", make_fake_requests_get(responses)
        )

        result = scrape_element_main(website_url=url, css_element="p")

        assert result == f"Redirects to {target} — call again with that URL"

    def test_redirect_loop_hits_hop_cap(self, monkeypatch):
        url = "http://example.com/page"
        responses = {
            url: FakeResponse(status_code=302, headers={"location": url}),
        }
        monkeypatch.setattr(
            scrape_element_module.requests, "get", make_fake_requests_get(responses)
        )

        result = scrape_element_main(website_url=url, css_element="p")

        assert "exceeded max redirects" in result
        assert str(scrape_element_module.MAX_REDIRECTS) in result
