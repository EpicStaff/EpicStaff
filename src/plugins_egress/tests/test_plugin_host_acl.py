"""plugin_host_acl.py as Squid runs it: one long-lived child process, fed `<user> <host> -` lines."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parents[1] / "plugin_host_acl.py"

POLICY = {
    "weather": ["geocoding-api.open-meteo.com", "*.wikipedia.org"],
    "notes": ["api.github.com"],
    "quiet": [],
}


class Helper:
    """The helper process, kept open and asked one line at a time, as Squid keeps it."""

    def __init__(self, policy_path: Path):
        self.process = subprocess.Popen(
            [sys.executable, "-I", str(HELPER), str(policy_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def ask_line(self, line: bytes) -> str:
        self.process.stdin.write(line + b"\n")
        self.process.stdin.flush()
        return self.process.stdout.readline().decode("ascii").rstrip("\n")

    def ask(self, user: str, host: str) -> str:
        return self.ask_line(f"{user} {host} -".encode())

    def close(self) -> str:
        """Close stdin as Squid does; return what the helper logged."""
        self.process.stdin.close()
        log = self.process.stderr.read().decode()
        assert self.process.wait(timeout=10) == 0, log
        return log


def write_policy(path: Path, content) -> None:
    """Replace the policy file as the plugin node does: a new file renamed over the old one."""
    temporary = path.with_name(f".{path.name}.new")
    temporary.write_bytes(content if isinstance(content, bytes) else json.dumps(content).encode())
    os.replace(temporary, path)


@pytest.fixture
def policy_path(tmp_path):
    path = tmp_path / "hosts.json"
    write_policy(path, POLICY)
    return path


@pytest.fixture
def helper(policy_path):
    started = Helper(policy_path)
    yield started
    if not started.process.stdin.closed:
        started.close()


def test_a_plugin_reaches_the_exact_hosts_on_its_own_list_only(helper):
    assert helper.ask("weather", "geocoding-api.open-meteo.com") == "OK"
    assert helper.ask("notes", "api.github.com") == "OK"
    assert helper.ask("weather", "api.github.com") == "ERR"
    assert helper.ask("notes", "geocoding-api.open-meteo.com") == "ERR"
    assert helper.ask("quiet", "geocoding-api.open-meteo.com") == "ERR"
    assert helper.ask("nobody", "geocoding-api.open-meteo.com") == "ERR"
    assert helper.ask("weather", "open-meteo.com") == "ERR"
    assert helper.ask("weather", "api.geocoding-api.open-meteo.com") == "ERR"


def test_a_wildcard_entry_covers_subdomains_at_any_depth_but_never_the_apex(helper):
    assert helper.ask("weather", "de.wikipedia.org") == "OK"
    assert helper.ask("weather", "upload.de.m.wikipedia.org") == "OK"
    assert helper.ask("weather", "wikipedia.org") == "ERR"


@pytest.mark.parametrize(
    "host",
    ["evilwikipedia.org", "wikipedia.org.evil.example", "de.wikipedia.org.evil.example", "wikipedia.orgx"],
)
def test_a_wildcard_entry_is_no_suffix_match(helper, host):
    assert helper.ask("weather", host) == "ERR"


@pytest.mark.parametrize("host", [".wikipedia.org", "de..wikipedia.org", "geocoding-api.open-meteo.com..", ""])
def test_a_name_with_an_empty_label_is_refused(helper, host):
    assert helper.ask_line(f"weather {host} -".encode() if host else b"weather  -") == "ERR"


def test_hosts_and_entries_are_compared_lower_cased_and_without_a_trailing_dot(tmp_path):
    path = tmp_path / "hosts.json"
    write_policy(path, {"Weather": ["API.GitHub.com."], "weather": ["*.Wikipedia.ORG"]})
    helper = Helper(path)

    assert helper.ask("weather", "GEOCODING-API.Open-Meteo.com") == "ERR"
    assert helper.ask("Weather", "api.github.com") == "OK"
    assert helper.ask("Weather", "API.GITHUB.COM.") == "OK"
    assert helper.ask("weather", "De.WIKIPEDIA.org.") == "OK"
    # Users are compared exactly: Squid runs with casesensitive on.
    assert helper.ask("weather", "api.github.com") == "ERR"
    assert helper.ask("WEATHER", "de.wikipedia.org") == "ERR"
    helper.close()


def test_the_brackets_of_an_ipv6_literal_are_removed(tmp_path):
    path = tmp_path / "hosts.json"
    write_policy(path, {"weather": ["2001:db8::1"]})
    helper = Helper(path)

    assert helper.ask("weather", "[2001:db8::1]") == "OK"
    assert helper.ask("weather", "2001:db8::1") == "OK"
    assert helper.ask("weather", "[2001:db8::1") == "ERR"
    assert helper.ask("weather", "[2001:db8::2]") == "ERR"
    helper.close()


def test_url_escapes_are_decoded_before_the_comparison(helper):
    assert helper.ask("%77eather", "geocoding%2Dapi.open-meteo.com") == "OK"
    assert helper.ask("weather", "de%2Ewikipedia%2Eorg") == "OK"
    assert helper.ask("weather", "wikipedia%2Eorg") == "ERR"


@pytest.mark.parametrize(
    "host",
    [
        "geocoding-api.open-meteo.com%20",
        "geocoding-api.open-meteo.com%00",
        "geocoding-api.open-meteo.com%0A",
        "geocoding-api.open-meteo.com%2F",
        "geocoding-api.open-meteo.com%ff",
        "%C3%A9geocoding-api.open-meteo.com",
    ],
)
def test_an_escape_that_decodes_to_anything_else_is_refused(helper, host):
    assert helper.ask("weather", host) == "ERR"


@pytest.mark.parametrize(
    "line",
    [
        b"",
        b"weather",
        b"weather geocoding-api.open-meteo.com",
        b"weather geocoding-api.open-meteo.com - extra",
        b"weather geocoding-api.open-meteo.com x",
        b"weather geocoding-api.open-meteo.com --",
        b"- geocoding-api.open-meteo.com -",
        "weathér geocoding-api.open-meteo.com -".encode(),
        b"weather \xffgeocoding-api.open-meteo.com -",
    ],
)
def test_a_line_of_any_other_shape_is_refused_and_the_helper_keeps_answering(helper, line):
    assert helper.ask_line(line) == "ERR"
    assert helper.ask("weather", "geocoding-api.open-meteo.com") == "OK"


def test_it_never_exits_on_garbage(helper):
    for line in (b"\x00\x01\x02", b"%" * 50_000, b"a " * 10_000, bytes(range(1, 10)) + bytes(range(11, 256))):
        assert helper.ask_line(line) == "ERR"
    assert helper.ask("weather", "geocoding-api.open-meteo.com") == "OK"
    log = helper.close()
    assert "Traceback" not in log


def test_a_missing_policy_file_refuses_everyone(tmp_path):
    helper = Helper(tmp_path / "missing.json")

    assert helper.ask("weather", "geocoding-api.open-meteo.com") == "ERR"
    assert "policy file unreadable (FileNotFoundError); refusing everyone" in helper.close()


def test_an_unreadable_policy_file_refuses_everyone(tmp_path):
    # A directory where the file should be: unreadable for root too.
    (tmp_path / "hosts.json").mkdir()
    helper = Helper(tmp_path / "hosts.json")

    assert helper.ask("weather", "geocoding-api.open-meteo.com") == "ERR"
    assert "refusing everyone" in helper.close()


@pytest.mark.parametrize(
    "content",
    [
        b"{not json",
        b"\xff\xfe{}",
        json.dumps([["weather", "geocoding-api.open-meteo.com"]]).encode(),
        json.dumps({"weather": "geocoding-api.open-meteo.com"}).encode(),
        json.dumps({"weather": ["geocoding-api.open-meteo.com", 7]}).encode(),
        json.dumps({"weather": ["geocoding-api.open-meteo.com"], "notes": None}).encode(),
    ],
)
def test_a_policy_file_of_any_other_shape_refuses_everyone(policy_path, helper, content):
    assert helper.ask("weather", "geocoding-api.open-meteo.com") == "OK"

    write_policy(policy_path, content)

    assert helper.ask("weather", "geocoding-api.open-meteo.com") == "ERR"
    assert helper.ask("notes", "api.github.com") == "ERR"
    assert "policy file invalid" in helper.close()


def test_the_policy_is_read_again_after_the_node_replaces_it(policy_path, helper):
    assert helper.ask("weather", "geocoding-api.open-meteo.com") == "OK"
    assert helper.ask("weather", "api.open-meteo.com") == "ERR"

    write_policy(policy_path, {"weather": ["api.open-meteo.com"]})

    assert helper.ask("weather", "geocoding-api.open-meteo.com") == "ERR"
    assert helper.ask("weather", "api.open-meteo.com") == "OK"
    assert helper.ask("notes", "api.github.com") == "ERR"


def test_the_helper_recovers_once_a_missing_or_invalid_policy_is_valid_again(policy_path, helper):
    policy_path.unlink()
    assert helper.ask("weather", "geocoding-api.open-meteo.com") == "ERR"
    write_policy(policy_path, b"[]")
    assert helper.ask("weather", "geocoding-api.open-meteo.com") == "ERR"

    write_policy(policy_path, POLICY)

    assert helper.ask("weather", "geocoding-api.open-meteo.com") == "OK"


def test_only_counts_are_logged(policy_path, helper):
    helper.ask("weather", "geocoding-api.open-meteo.com")
    helper.ask_line(b"weather geocoding-api.open-meteo.com")
    write_policy(policy_path, b"{not json")
    helper.ask("weather", "geocoding-api.open-meteo.com")

    log = helper.close()

    assert "policy loaded: 3 plugins, 3 hosts" in log
    for name in ("weather", "notes", "geocoding", "wikipedia", "github"):
        assert name not in log


def test_without_a_policy_path_it_refuses_to_start():
    finished = subprocess.run([sys.executable, "-I", str(HELPER)], capture_output=True, text=True, timeout=10)

    assert finished.returncode == 2
    assert "usage: plugin_host_acl <hosts.json>" in finished.stderr
