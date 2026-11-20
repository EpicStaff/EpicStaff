"""The txt, xml and github search tools fetch an agent-supplied URL, so each must
refuse internal addresses and never follow a redirect into one.

Each tool carries its own copy of the guard (kept in sync by
test_ssrf_guard_drift.py); this file checks the copies through each main().
"""

import socket
import subprocess

import pytest
from conftest import FakeResponse, load_tool_main, make_fake_requests_get

INTERNAL_HOST = "internal.example"
DOCUMENT_URL = "http://example.com/document"

FETCHING_TOOLS = {
    "crewai_txt_search_tool_tool": lambda module, url: module.main(txt=url, search_query="needle"),
    "crewai_xml_search_tool": lambda module, url: module.main(search_query="needle", xml=url),
}
EACH_FETCHING_TOOL = pytest.mark.parametrize("tool_dir_name", list(FETCHING_TOOLS))

DOCUMENT_BODIES = {
    "crewai_txt_search_tool_tool": "first line\nneedle in a line\n",
    "crewai_xml_search_tool": "<root><item>needle in a line</item></root>",
}

UNSAFE_URLS = pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://10.0.0.5/",
        "http://169.254.169.254/latest/meta-data/",
        f"http://{INTERNAL_HOST}/",
    ],
    ids=["loopback", "private", "cloud-metadata", "host-resolving-to-private"],
)


@pytest.fixture(autouse=True)
def internal_host_resolves_to_private_address(monkeypatch):
    real_getaddrinfo = socket.getaddrinfo

    def getaddrinfo(host, *args, **kwargs):
        if host == INTERNAL_HOST:
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("10.0.0.5", 0))]
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


@EACH_FETCHING_TOOL
@UNSAFE_URLS
def test_internal_url_is_refused_before_any_request(tool_dir_name, url, monkeypatch):
    module = load_tool_main(tool_dir_name)
    requested = []

    def recording_get(requested_url, **kwargs):
        requested.append(requested_url)
        return FakeResponse(text="internal-only response")

    monkeypatch.setattr(module.requests, "get", recording_get)

    result = FETCHING_TOOLS[tool_dir_name](module, url)

    assert result.startswith("Error:")
    assert "private/internal address" in result
    assert "internal-only response" not in result
    assert requested == []


@EACH_FETCHING_TOOL
@pytest.mark.parametrize("target", ["http://169.254.169.254/", f"http://{INTERNAL_HOST}/"], ids=["metadata", "private-host"])
def test_redirect_to_internal_address_is_not_followed(tool_dir_name, target, monkeypatch):
    module = load_tool_main(tool_dir_name)
    requested = []
    redirect_only = make_fake_requests_get(
        {DOCUMENT_URL: FakeResponse(status_code=302, headers={"location": target})}
    )

    def recording_get(requested_url, **kwargs):
        requested.append(requested_url)
        return redirect_only(requested_url, **kwargs)

    monkeypatch.setattr(module.requests, "get", recording_get)

    result = FETCHING_TOOLS[tool_dir_name](module, DOCUMENT_URL)

    assert result == f"Redirects to {target} — call again with that URL"
    assert requested == [DOCUMENT_URL]


@EACH_FETCHING_TOOL
def test_same_host_redirect_is_followed_and_searched(tool_dir_name, monkeypatch):
    module = load_tool_main(tool_dir_name)
    monkeypatch.setattr(module.requests, "get", make_fake_requests_get({
        DOCUMENT_URL: FakeResponse(status_code=301, headers={"location": "/moved"}),
        "http://example.com/moved": FakeResponse(text=DOCUMENT_BODIES[tool_dir_name]),
    }))

    assert "needle in a line" in FETCHING_TOOLS[tool_dir_name](module, DOCUMENT_URL)


@EACH_FETCHING_TOOL
def test_http_error_status_is_reported_as_an_error(tool_dir_name, monkeypatch):
    module = load_tool_main(tool_dir_name)
    monkeypatch.setattr(module.requests, "get", make_fake_requests_get({
        DOCUMENT_URL: FakeResponse(status_code=404),
    }))

    result = FETCHING_TOOLS[tool_dir_name](module, DOCUMENT_URL)

    assert result.startswith("Error:") and "404" in result


@UNSAFE_URLS
def test_github_internal_url_is_refused_without_cloning(url, monkeypatch):
    module = load_tool_main("crewai_github_search_tool")
    commands = []
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: commands.append(command))

    result = module.main(search_query="needle", repo_path_or_url=url)

    assert result.startswith("Error:")
    assert "private/internal address" in result
    assert commands == []


def test_github_clone_does_not_follow_redirects(monkeypatch):
    module = load_tool_main("crewai_github_search_tool")
    commands = []
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: commands.append(command))

    module.main(search_query="needle", repo_path_or_url="https://github.com/org/repo")

    [command] = commands
    assert command[:3] == ["git", "-c", "http.followRedirects=false"]
    assert "clone" in command


PUBLIC_HOST = "public.example"


def _answer(*ips):
    return [
        (socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 0))
        for ip in ips
    ]


def _record_clone_commands(monkeypatch):
    commands = []
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: commands.append(command))
    return commands


@pytest.mark.parametrize(
    "url, expected_entry",
    [
        (f"https://{PUBLIC_HOST}/org/repo", f"{PUBLIC_HOST}:443:93.184.216.34"),
        (f"https://{PUBLIC_HOST}:8443/org/repo", f"{PUBLIC_HOST}:8443:93.184.216.34"),
        (f"http://{PUBLIC_HOST}/org/repo", f"{PUBLIC_HOST}:80:93.184.216.34"),
        (f"http://{PUBLIC_HOST}:8080/org/repo", f"{PUBLIC_HOST}:8080:93.184.216.34"),
    ],
)
def test_github_clone_is_pinned_to_the_vetted_address(url, expected_entry, monkeypatch):
    module = load_tool_main("crewai_github_search_tool")
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, *args, **kwargs: _answer("93.184.216.34"))
    commands = _record_clone_commands(monkeypatch)

    module.main(search_query="needle", repo_path_or_url=url)

    [command] = commands
    assert command[:5] == [
        "git",
        "-c",
        "http.followRedirects=false",
        "-c",
        f"http.curloptResolve={expected_entry}",
    ]
    assert command[5:8] == ["clone", "--depth", "1"]
    assert command[8] == url


def test_github_clone_pins_the_first_address_of_the_answer(monkeypatch):
    module = load_tool_main("crewai_github_search_tool")
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda host, *args, **kwargs: _answer("93.184.216.34", "93.184.216.35")
    )
    commands = _record_clone_commands(monkeypatch)

    module.main(search_query="needle", repo_path_or_url=f"https://{PUBLIC_HOST}/org/repo")

    [command] = commands
    assert f"http.curloptResolve={PUBLIC_HOST}:443:93.184.216.34" in command


def test_github_clone_brackets_a_public_ipv6_address(monkeypatch):
    module = load_tool_main("crewai_github_search_tool")
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda host, *args, **kwargs: _answer("2606:2800:220:1:248:1893:25c8:1946")
    )
    commands = _record_clone_commands(monkeypatch)

    module.main(search_query="needle", repo_path_or_url=f"https://{PUBLIC_HOST}/org/repo")

    [command] = commands
    assert f"http.curloptResolve={PUBLIC_HOST}:443:[2606:2800:220:1:248:1893:25c8:1946]" in command


def test_github_rebinding_host_is_never_cloned_unpinned_or_to_an_internal_address(monkeypatch):
    module = load_tool_main("crewai_github_search_tool")
    answers = iter([_answer("93.184.216.34"), _answer("10.0.0.5")])
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, *args, **kwargs: next(answers, _answer("10.0.0.5")))
    commands = _record_clone_commands(monkeypatch)

    result = module.main(search_query="needle", repo_path_or_url=f"https://{PUBLIC_HOST}/org/repo")

    for command in commands:
        resolve_options = [part for part in command if part.startswith("http.curloptResolve=")]
        assert resolve_options == [f"http.curloptResolve={PUBLIC_HOST}:443:93.184.216.34"]
    if not commands:
        assert result.startswith("Error:") and "private/internal address" in result


@pytest.mark.parametrize("answer", [("93.184.216.34", "10.0.0.5"), ("::1",), ("93.184.216.34", "169.254.169.254")])
def test_github_host_with_any_internal_address_is_refused(answer, monkeypatch):
    module = load_tool_main("crewai_github_search_tool")
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, *args, **kwargs: _answer(*answer))
    commands = _record_clone_commands(monkeypatch)

    result = module.main(search_query="needle", repo_path_or_url=f"https://{PUBLIC_HOST}/org/repo")

    assert result.startswith("Error:") and "private/internal address" in result
    assert commands == []


def test_github_non_ascii_host_is_refused_without_cloning(monkeypatch):
    module = load_tool_main("crewai_github_search_tool")
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, *args, **kwargs: _answer("93.184.216.34"))
    commands = _record_clone_commands(monkeypatch)

    result = module.main(search_query="needle", repo_path_or_url="https://bücher.example/org/repo")

    assert result.startswith("Error:") and "not an ASCII host name" in result
    assert commands == []


def test_github_host_that_fails_to_resolve_at_pin_time_returns_an_error(monkeypatch):
    module = load_tool_main("crewai_github_search_tool")
    calls = []

    def getaddrinfo(host, *args, **kwargs):
        calls.append(host)
        if len(calls) == 1:
            return _answer("93.184.216.34")
        raise socket.gaierror(-2, "Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    commands = _record_clone_commands(monkeypatch)

    result = module.main(search_query="needle", repo_path_or_url=f"https://{PUBLIC_HOST}/org/repo")

    assert result.startswith("Error: could not resolve host")
    assert commands == []
