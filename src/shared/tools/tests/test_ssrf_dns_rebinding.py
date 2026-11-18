"""A host that resolves public for `_ssrf_guard` and internal when the HTTP
client connects (DNS rebinding) must not reach the internal address.

Real httpx / requests talk to a loopback HTTP server here: the mocked
transports in the other tool tests never resolve a host, so they cannot show
that the connect-time check sits on the connection path.
"""

import http.server
import socket
import threading

import pytest
import requests
from conftest import load_tool_main

INTERNAL_BODY = "internal-only response"
PUBLIC_IP = "93.184.216.34"
REBINDING_HOST = "rebinding.example"


class _InternalService(http.server.BaseHTTPRequestHandler):
    def _respond(self):
        body = INTERNAL_BODY.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = _respond
    do_POST = _respond

    def log_message(self, *args):
        pass


@pytest.fixture
def internal_url():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _InternalService)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://{REBINDING_HOST}:{server.server_address[1]}/"
    server.shutdown()
    server.server_close()


@pytest.fixture
def rebinding_resolver(monkeypatch):
    """Answer the first lookup of the host with a public address, every later one with loopback."""
    real_getaddrinfo = socket.getaddrinfo
    lookups = []

    def getaddrinfo(host, port, *args, **kwargs):
        if host != REBINDING_HOST:
            return real_getaddrinfo(host, port, *args, **kwargs)
        lookups.append(host)
        address = PUBLIC_IP if len(lookups) == 1 else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port or 0))]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    return getaddrinfo


# Each tool's guarded request step rather than main(): web_fetch upgrades http
# to https, and Jina sends the request to its public proxy instead of the URL.
def _web_fetch(module, url):
    content, error = module._fetch_and_convert(url)
    return content or error


def _notification_webhook(module, url):
    return module._send_webhook("hello", url, "")


def _scraper_get(module, url):
    try:
        response, error = module._guarded_get(url)
    except requests.ConnectionError as connection_error:
        return str(connection_error)
    return response.text if response is not None else error


REQUEST_STEPS = {
    "web_fetch_tool": _web_fetch,
    "notification_tool": _notification_webhook,
    "crewai_scrape_website_tool": _scraper_get,
    "crewai_scrape_element_from_website_tool": _scraper_get,
    "crewai_jina_scraper_website_tool": _scraper_get,
    "crewai_website_search_tool": _scraper_get,
}


@pytest.mark.parametrize("tool_dir_name", list(REQUEST_STEPS))
def test_rebinding_to_internal_address_is_refused_at_connect(
    tool_dir_name, internal_url, rebinding_resolver
):
    module = load_tool_main(tool_dir_name)

    result = REQUEST_STEPS[tool_dir_name](module, internal_url)

    assert INTERNAL_BODY not in result
    assert "private/internal address (127.0.0.1)" in result


@pytest.mark.parametrize("tool_dir_name", list(REQUEST_STEPS))
def test_resolver_is_restored_after_a_refused_connect(
    tool_dir_name, internal_url, rebinding_resolver
):
    module = load_tool_main(tool_dir_name)

    REQUEST_STEPS[tool_dir_name](module, internal_url)

    assert socket.getaddrinfo is rebinding_resolver
