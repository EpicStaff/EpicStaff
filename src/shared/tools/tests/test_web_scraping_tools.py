"""The four website tools share one contract for fetching agent-supplied URLs.

Each tool is uploaded as standalone source, so each carries its own copy of the
SSRF guard and the redirect-following fetch (kept in sync by
test_ssrf_guard_drift.py); this file checks every copy through each tool's main().
"""

from dataclasses import dataclass
from typing import Callable

import pytest
from conftest import FakeResponse, load_tool_main, make_fake_requests_get

PAGE = "http://example.com/page"


@dataclass
class WebTool:
    name: str
    call: Callable[[object, str], str]
    # The URL the tool actually requests for a page (Jina goes through its proxy).
    fetched: Callable[[str], str]
    same_host_target: str
    page_body: str
    expected: Callable[[str], bool]

    @property
    def module(self):
        return load_tool_main(self.name)


TOOLS = [
    WebTool(
        "crewai_scrape_website_tool",
        lambda module, url: module.main(website_url=url),
        lambda url: url, "https://example.com/page",
        "<html><body><p>Hello</p></body></html>", lambda result: "Hello" in result,
    ),
    WebTool(
        "crewai_scrape_element_from_website_tool",
        lambda module, url: module.main(website_url=url, css_element="p"),
        lambda url: url, "https://example.com/page",
        "<html><body><p>Hello</p></body></html>", lambda result: result == "Hello",
    ),
    WebTool(
        "crewai_website_search_tool",
        lambda module, url: module.main(search_query="needle", website=url),
        lambda url: url, "https://example.com/page",
        "<html><body><p>needle in a haystack</p></body></html>", lambda result: "needle in a haystack" in result,
    ),
    WebTool(
        "crewai_jina_scraper_website_tool",
        lambda module, url: module.main(website_url=url, api_key="test-key"),
        lambda url: f"https://r.jina.ai/{url}", "https://r.jina.ai/other-path",
        "markdown content", lambda result: result == "markdown content",
    ),
]
EACH_TOOL = pytest.mark.parametrize("tool", TOOLS, ids=[tool.name for tool in TOOLS])


@EACH_TOOL
@pytest.mark.parametrize(
    ("url", "reason"),
    [("http://127.0.0.1/", "SSRF"), ("http://169.254.169.254/", "SSRF"), ("ftp://example.com/file", "scheme")],
    ids=["loopback", "cloud-metadata", "non-http-scheme"],
)
def test_unsafe_url_is_refused_before_any_request(tool, monkeypatch, url, reason):
    """For Jina the agent's URL itself is checked, not the always-public proxy URL."""
    module = tool.module
    monkeypatch.setattr(module.requests, "get", make_fake_requests_get({}))

    result = tool.call(module, url)

    assert result.startswith("Error:")
    assert reason in result


@EACH_TOOL
def test_same_host_redirect_is_followed(tool, monkeypatch):
    module = tool.module
    monkeypatch.setattr(module.requests, "get", make_fake_requests_get({
        tool.fetched(PAGE): FakeResponse(status_code=301, headers={"location": tool.same_host_target}),
        tool.same_host_target: FakeResponse(status_code=200, text=tool.page_body),
    }))

    assert tool.expected(tool.call(module, PAGE))


@EACH_TOOL
@pytest.mark.parametrize(
    "target",
    ["http://127.0.0.1/", "http://evil.example.net/"],
    ids=["to-loopback", "to-another-host"],
)
def test_redirect_off_the_host_is_handed_back_to_the_agent(tool, monkeypatch, target):
    """The agent must call again with the new URL, so it passes the guard again."""
    module = tool.module
    monkeypatch.setattr(module.requests, "get", make_fake_requests_get({
        tool.fetched(PAGE): FakeResponse(status_code=302, headers={"location": target}),
    }))

    assert tool.call(module, PAGE) == f"Redirects to {target} — call again with that URL"


@EACH_TOOL
def test_redirect_loop_stops_at_the_hop_cap(tool, monkeypatch):
    module = tool.module
    fetched = tool.fetched(PAGE)
    monkeypatch.setattr(module.requests, "get", make_fake_requests_get({
        fetched: FakeResponse(status_code=302, headers={"location": fetched}),
    }))

    result = tool.call(module, PAGE)

    assert "exceeded max redirects" in result
    assert str(module.MAX_REDIRECTS) in result
