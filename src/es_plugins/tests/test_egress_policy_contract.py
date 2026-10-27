"""The policy the node writes, read by the egress proxy's own host helper.

The helper is `src/plugins_egress/plugin_host_acl.py`, the file the proxy image installs. It is
fed the lines Squid sends it, `<user> <host> -`, for the `hosts.json` the agent's writer made.
"""

import subprocess
import sys
from pathlib import Path

from es_plugins.egress.policy_writer import HOSTS_FILE_NAME, EgressPolicyWriter

HOST_HELPER = Path(__file__).resolve().parents[2] / "plugins_egress" / "plugin_host_acl.py"


def ask_helper(policy_file: Path, requests: list[tuple[str, str]]) -> list[str]:
    lines = "".join(f"{user} {host} -\n" for user, host in requests)
    answered = subprocess.run(
        [sys.executable, "-I", str(HOST_HELPER), str(policy_file)],
        input=lines,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return answered.stdout.splitlines()


async def test_the_proxy_allows_each_plugin_exactly_the_hosts_the_node_wrote_for_it(tmp_path):
    writer = EgressPolicyWriter(tmp_path)
    await writer.start()
    await writer.write_hosts(
        {
            "weather": ["geocoding-api.open-meteo.com", "*.wikipedia.org"],
            "other": ["api.github.com"],
            "notes": [],
        }
    )
    expected = {
        ("weather", "geocoding-api.open-meteo.com"): "OK",
        ("weather", "de.wikipedia.org"): "OK",
        ("weather", "wikipedia.org"): "ERR",
        ("weather", "evilwikipedia.org"): "ERR",
        ("weather", "api.github.com"): "ERR",
        ("other", "api.github.com"): "OK",
        ("other", "geocoding-api.open-meteo.com"): "ERR",
        ("notes", "example.com"): "ERR",
        ("nobody", "geocoding-api.open-meteo.com"): "ERR",
    }

    answers = ask_helper(tmp_path / HOSTS_FILE_NAME, list(expected))

    assert dict(zip(expected, answers, strict=True)) == expected


async def test_the_empty_policy_of_an_agent_start_refuses_everyone(tmp_path):
    writer = EgressPolicyWriter(tmp_path)
    await writer.start()

    assert ask_helper(tmp_path / HOSTS_FILE_NAME, [("weather", "geocoding-api.open-meteo.com")]) == ["ERR"]
