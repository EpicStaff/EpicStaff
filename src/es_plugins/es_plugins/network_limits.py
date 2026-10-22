"""Per-plugin limits on the node's TCP connections, set once at start-up.

PostgreSQL takes one of its `max_connections` slots for a connection before it authenticates
it, and keeps it until the client answers or `authentication_timeout` passes. A role's
`CONNECTION LIMIT` and `reserved_connections` apply only after login. So, uncapped, one plugin
that keeps opening connections and never answers the password challenge would hold every slot,
the five kept for the plugin node included. The egress proxy checks a password for every
request it is sent, so a plugin that floods it slows every other plugin's outbound access.

Every plugin and the agent share the container's one network namespace, and with it its
ephemeral ports (21000-65535, about 44,500). A socket holds one from the moment it is bound,
before any packet is sent: `bind()` to port 0, `listen()` on an unbound TCP socket or a UDP
`connect()` takes one silently, and a TCP connection takes one until about a minute after it
closes. Without limits one plugin could take them all, and the agent could reach neither
django_app nor plugins_db, so the plugin could not even be suspended.

At start-up, for each plugin UID:

- **No `bind()` of an inet socket** (`bind_refusal`). A plugin serves on the socket the agent
  hands it as fd 3 and never needs to bind one.
- **One nftables table** in the container's network namespace:
  - at most `NEW_CONNECTIONS_PER_SECOND` new TCP connections a second, to anywhere, after a
    burst of `NEW_CONNECTIONS_BURST`;
  - at most `TCP_CONNECTIONS_PER_PLUGIN` TCP connections it opened open at once, to anywhere
    (its own port included); a connection it accepts is not counted, since its first packet
    leaves in conntrack's reply direction;
  - at most `PLUGINS_MAX_DB_CONNECTIONS` of them to plugins_db, and
    `PROXY_CONNECTIONS_PER_PLUGIN` to the egress proxy.

  A connection over a limit is refused at once (a TCP reset), and closed connections stop
  counting.

What these cannot see is a port the kernel takes for a socket without `bind()`: `listen()` on an
unbound TCP socket, and a UDP socket connected without sending. The descriptor limits do not bound
it either (`RLIMIT_NOFILE` 256 is per process, `RLIMIT_NPROC` 64 per UID: about 16,000 sockets per
plugin). The agent's socket watchdog (`supervisor.socket_watchdog`) stops a plugin whose UID
listens on a port of its own, or holds more inet sockets than twice `TCP_CONNECTIONS_PER_PLUGIN`
plus a UDP allowance (the connections it accepted on its own port not counted), within a second;
up to one second of such port pressure is the risk that remains. The agent's UID is outside
`PLUGINS_NODE_UID_RANGE`, so the node's own sockets are never limited.

The container's entrypoint runs `python -m es_plugins.network_limits` as root with NET_ADMIN and
BPF, then starts the launcher without NET_ADMIN, BPF or SETPCAP in any capability set, so nothing
that runs on the node afterwards can change the limits.
"""

import json
import os
import shutil
import subprocess
import sys

from loguru import logger

from es_plugins.bind_refusal import BindRefusalError, install_bind_refusal
from es_plugins.egress.policy_writer import EGRESS_PROXY_PORT
from es_plugins.logging_setup import configure_logging
from es_plugins.uid_range import UidRange

TABLE_FAMILY = "inet"
TABLE_NAME = "es_plugins_limits"
# plugins_db's port in src/docker-compose.yaml; django_app registers the server with it.
PLUGINS_DB_PORT = 5432
# A plugin's outbound requests are few and short; this leaves room for a busy one, not a flood.
PROXY_CONNECTIONS_PER_PLUGIN = 64
# Far above what a plugin needs, far below what exhausts the shared ephemeral ports (about
# 44,500, each held about a minute after it closes).
NEW_CONNECTIONS_PER_SECOND = 200
NEW_CONNECTIONS_BURST = 200
# Far above a plugin's database, proxy and loopback connections together.
TCP_CONNECTIONS_PER_PLUGIN = 512
# No plugin's database connection limit is above this: the manifest and the node contract bound it.
MAXIMUM_DATABASE_CONNECTIONS = 100
NFT_TIMEOUT_SECONDS = 30
EXIT_CONFIGURATION_ERROR = 64


class NetworkLimitsError(Exception):
    """The caps could not be installed, or are not in place afterwards; the message says why."""


def connection_limits_ruleset(uid_range: UidRange, database_connections: int) -> str:
    """The nftables script that (re)creates the caps for the plugin UIDs of `uid_range`.

    It replaces the table as one transaction: the first two lines make sure the table exists,
    so the delete never fails, and the caps are never missing in between.
    """
    uids = f"{uid_range.first}-{uid_range.last}"
    caps = _caps(database_connections)
    sets = "".join(
        f"    set {name} {{\n"
        "        typeof meta skuid\n"
        "        size 65535\n"
        "        flags dynamic\n"
        "    }\n"
        for name in ("new_connections", *(name for name, _, _ in caps))
    )
    rules = f"        {_rate_rule(uids)}\n" + "".join(
        f"        {_cap_rule(uids, name, port, limit)}\n" for name, port, limit in caps
    )
    return (
        f"table {TABLE_FAMILY} {TABLE_NAME}\n"
        f"delete table {TABLE_FAMILY} {TABLE_NAME}\n"
        f"table {TABLE_FAMILY} {TABLE_NAME} {{\n"
        f"{sets}"
        "    chain output {\n"
        "        type filter hook output priority filter; policy accept;\n"
        f"{rules}"
        "    }\n"
        "}\n"
    )


def _caps(database_connections: int) -> tuple[tuple[str, int | None, int], ...]:
    """(set, port or None for every TCP connection, limit) of each cap on open connections."""
    return (
        ("tcp_connections", None, TCP_CONNECTIONS_PER_PLUGIN),
        ("database_connections", PLUGINS_DB_PORT, database_connections),
        ("proxy_connections", EGRESS_PROXY_PORT, PROXY_CONNECTIONS_PER_PLUGIN),
    )


def _rate_rule(uids: str) -> str:
    return (
        f"meta skuid {uids} meta l4proto tcp ct state new add @new_connections "
        f"{{ meta skuid limit rate over {NEW_CONNECTIONS_PER_SECOND}/second "
        f"burst {NEW_CONNECTIONS_BURST} packets }} counter reject with tcp reset"
    )


def _cap_rule(uids: str, set_name: str, port: int | None, limit: int) -> str:
    destination = f"tcp dport {port}" if port is not None else "meta l4proto tcp"
    return (
        f"meta skuid {uids} {destination} ct state new "
        f"add @{set_name} {{ meta skuid ct count over {limit} }} counter reject with tcp reset"
    )


def install_connection_limits(uid_range: UidRange, database_connections: int) -> None:
    """Install the caps and check that the kernel holds them as written.

    Raises:
        NetworkLimitsError: `nft` is missing or refused the script (no NET_ADMIN, or a kernel
            without the nftables connection counter), or the table it lists afterwards lacks
            a cap.
    """
    nft = shutil.which("nft")
    if nft is None:
        raise NetworkLimitsError("nft is not installed")
    loaded = _run_nft(nft, ["-f", "-"], connection_limits_ruleset(uid_range, database_connections))
    if loaded.returncode != 0:
        raise NetworkLimitsError(f"nft refused the connection caps: {_one_line(loaded.stderr)}")
    listed = _run_nft(nft, ["-j", "list", "table", TABLE_FAMILY, TABLE_NAME])
    if listed.returncode != 0:
        raise NetworkLimitsError(
            f"the connection caps cannot be listed: {_one_line(listed.stderr)}"
        )
    try:
        installed = installed_rules(json.loads(listed.stdout))
    except (ValueError, KeyError, TypeError) as error:
        raise NetworkLimitsError(f"nft listed the connection caps unreadably: {error}") from None
    expected = expected_rules(uid_range, database_connections)
    if installed != expected:
        missing = sorted(str(rule) for rule in expected - installed)
        raise NetworkLimitsError(
            "the connection caps are not as installed: "
            + (f"missing {'; '.join(missing)}" if missing else "the table holds other rules")
        )


Rule = tuple
"""What a rule of the table does, read from `nft -j` (libnftables' documented JSON): the UID range,
the port (None for every TCP connection), the set, the limit, and whether it resets."""


def expected_rules(uid_range: UidRange, database_connections: int) -> set[Rule]:
    uids = (uid_range.first, uid_range.last)
    rate = ("rate", NEW_CONNECTIONS_PER_SECOND, NEW_CONNECTIONS_BURST, "second")
    return {
        (uids, None, "new_connections", rate, True),
        *(
            (uids, port, name, ("count", limit), True)
            for name, port, limit in _caps(database_connections)
        ),
    }


def installed_rules(listing: dict) -> set[Rule]:
    """The rules of the table's output chain, as `expected_rules` describes them."""
    rules = set()
    for item in listing["nftables"]:
        rule = item.get("rule")
        if rule is None or rule["chain"] != "output":
            continue
        uids = port = set_name = limit = None
        resets = False
        for expression in rule["expr"]:
            if "match" in expression:
                left, right = expression["match"]["left"], expression["match"]["right"]
                if left == {"meta": {"key": "skuid"}} and isinstance(right, dict):
                    uids = tuple(right["range"])
                elif left == {"payload": {"protocol": "tcp", "field": "dport"}}:
                    port = right
            elif "set" in expression:
                set_name = expression["set"]["set"].removeprefix("@")
                [statement] = expression["set"]["stmt"]
                if "limit" in statement and statement["limit"].get("inv"):
                    found = statement["limit"]
                    limit = ("rate", found["rate"], found["burst"], found["per"])
                elif "ct count" in statement and statement["ct count"].get("inv"):
                    limit = ("count", statement["ct count"]["val"])
            elif "reject" in expression:
                resets = expression["reject"].get("type") == "tcp reset"
        rules.add((uids, port, set_name, limit, resets))
    return rules


def _run_nft(nft: str, arguments: list[str], script: str | None = None):
    try:
        return subprocess.run(
            [nft, *arguments],
            input=script,
            capture_output=True,
            text=True,
            timeout=NFT_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise NetworkLimitsError(f"nft did not finish within {NFT_TIMEOUT_SECONDS} s") from None


def _one_line(text: str) -> str:
    return " ".join(text.split())[:500]


def database_connections_from(text: str) -> int:
    """The per-plugin cap to plugins_db for `PLUGINS_MAX_DB_CONNECTIONS`.

    django_app accepts any whole number above 0 there; no plugin gets more than
    `MAXIMUM_DATABASE_CONNECTIONS`, so neither does the cap.

    Raises:
        ValueError: It is not a whole number above 0.
    """
    value = text.strip()
    if not value.isascii() or not value.isdigit() or int(value) < 1:
        raise ValueError(f"PLUGINS_MAX_DB_CONNECTIONS={text!r} is not a whole number above 0")
    return min(int(value), MAXIMUM_DATABASE_CONNECTIONS)


def main() -> int:
    configure_logging("launcher")
    try:
        uid_range = UidRange.parse(os.environ.get("PLUGINS_NODE_UID_RANGE", ""))
        database_connections = database_connections_from(
            os.environ.get("PLUGINS_MAX_DB_CONNECTIONS", "")
        )
    except ValueError as error:
        logger.error("{}", error)
        return EXIT_CONFIGURATION_ERROR
    try:
        install_connection_limits(uid_range, database_connections)
        install_bind_refusal(uid_range)
    except (NetworkLimitsError, BindRefusalError) as error:
        logger.error("The per-plugin connection limits could not be set: {}", error)
        return 1
    logger.info(
        "plugins.node.connection_limits uids={}-{} database={} proxy={} tcp={} new_per_second={} "
        "bind=refused",
        uid_range.first,
        uid_range.last,
        database_connections,
        PROXY_CONNECTIONS_PER_PLUGIN,
        TCP_CONNECTIONS_PER_PLUGIN,
        NEW_CONNECTIONS_PER_SECOND,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
