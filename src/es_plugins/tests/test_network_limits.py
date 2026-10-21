"""The per-plugin connection caps: the ruleset, its settings, and (as root) the kernel holding it."""

import fcntl
import json
import os
import shutil
import socket
import struct
import time

import pytest

from es_plugins import network_limits
from es_plugins.layout import AGENT_UID
from es_plugins.network_limits import (
    EXIT_CONFIGURATION_ERROR,
    MAXIMUM_DATABASE_CONNECTIONS,
    NEW_CONNECTIONS_BURST,
    NEW_CONNECTIONS_PER_SECOND,
    PLUGINS_DB_PORT,
    PROXY_CONNECTIONS_PER_PLUGIN,
    NetworkLimitsError,
    connection_limits_ruleset,
    database_connections_from,
    install_connection_limits,
)
from es_plugins.uid_range import UidRange

UIDS = UidRange(20000, 20009)


def test_the_ruleset_caps_the_plugin_uids_only_on_both_ports():
    ruleset = connection_limits_ruleset(UIDS, 7)

    assert (
        "meta skuid 20000-20009 tcp dport 5432 ct state new "
        "add @database_connections { meta skuid ct count over 7 } counter reject with tcp reset"
    ) in ruleset
    assert (
        "meta skuid 20000-20009 tcp dport 3128 ct state new "
        f"add @proxy_connections {{ meta skuid ct count over {PROXY_CONNECTIONS_PER_PLUGIN} }} "
        "counter reject with tcp reset"
    ) in ruleset
    assert (
        "meta skuid 20000-20009 meta l4proto tcp ct state new add @new_connections "
        f"{{ meta skuid limit rate over {NEW_CONNECTIONS_PER_SECOND}/second burst {NEW_CONNECTIONS_BURST} packets }} "
        "counter reject with tcp reset"
    ) in ruleset
    # The rate comes first, so a flood is refused before it reaches the caps' counters.
    assert ruleset.index("@new_connections {") < ruleset.index("@database_connections {")
    assert AGENT_UID not in UIDS
    assert "policy accept" in ruleset


def test_the_ruleset_replaces_the_table_in_one_go():
    lines = connection_limits_ruleset(UIDS, 7).splitlines()

    assert lines[:3] == [
        "table inet es_plugins_limits",
        "delete table inet es_plugins_limits",
        "table inet es_plugins_limits {",
    ]


@pytest.mark.parametrize(("text", "cap"), [("20", 20), (" 5 ", 5), ("1", 1), ("500", MAXIMUM_DATABASE_CONNECTIONS)])
def test_the_database_cap_follows_the_platform_maximum_up_to_what_any_plugin_can_get(text, cap):
    assert database_connections_from(text) == cap


@pytest.mark.parametrize("text", ["", "0", "-3", "twenty", "2.5", "２０"])
def test_a_database_cap_that_is_not_a_whole_number_above_zero_is_refused(text):
    with pytest.raises(ValueError, match="PLUGINS_MAX_DB_CONNECTIONS"):
        database_connections_from(text)


@pytest.mark.parametrize(
    "environment",
    [
        {"PLUGINS_NODE_UID_RANGE": "20000-20999", "PLUGINS_MAX_DB_CONNECTIONS": "none"},
        {"PLUGINS_NODE_UID_RANGE": "5-9", "PLUGINS_MAX_DB_CONNECTIONS": "20"},
        {"PLUGINS_MAX_DB_CONNECTIONS": "20"},
    ],
)
def test_the_node_does_not_start_with_an_invalid_setting(monkeypatch, environment):
    monkeypatch.delenv("PLUGINS_NODE_UID_RANGE", raising=False)
    monkeypatch.delenv("PLUGINS_MAX_DB_CONNECTIONS", raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    assert network_limits.main() == EXIT_CONFIGURATION_ERROR


def test_without_nft_the_caps_are_refused_not_skipped(monkeypatch):
    monkeypatch.setattr(network_limits.shutil, "which", lambda name: None)

    with pytest.raises(NetworkLimitsError, match="nft is not installed"):
        install_connection_limits(UIDS, 3)


def _bring_up_loopback() -> None:
    siocgifflags, siocsifflags, iff_up = 0x8913, 0x8914, 0x1
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as control:
        request = struct.pack("16sH14s", b"lo", 0, b"")
        flags = struct.unpack("16sH14s", fcntl.ioctl(control, siocgifflags, request))[1]
        fcntl.ioctl(control, siocsifflags, struct.pack("16sH14s", b"lo", flags | iff_up, b""))


class _HeldConnections:
    """Connections a child opens as `uid` and keeps open until `release()`.

    Root without CAP_KILL cannot signal a plugin UID, so a child waits for its release pipe to
    close; each child closes the release pipes of the others it inherits.
    """

    _unreleased: list[int] = []

    def __init__(self, uid: int, port: int, count: int):
        reader, writer = os.pipe()
        release_reader, self._release = os.pipe()
        self._child = os.fork()
        if self._child == 0:
            os.close(self._release)
            for inherited in self._unreleased:
                os.close(inherited)
            opened = 0
            held = []
            try:
                os.setgroups([])
                os.setresgid(uid, uid, uid)
                os.setresuid(uid, uid, uid)
                for _ in range(count):
                    connection = socket.socket()
                    connection.settimeout(3)
                    try:
                        connection.connect(("127.0.0.1", port))
                        held.append(connection)
                        opened += 1
                    except OSError:
                        connection.close()
            finally:
                os.write(writer, str(opened).encode())
                os.close(writer)
                os.read(release_reader, 1)
                os._exit(0)
        os.close(writer)
        os.close(release_reader)
        self._unreleased.append(self._release)
        with os.fdopen(reader) as result:
            self.opened = int(result.read() or "0")

    def release(self) -> None:
        self._unreleased.remove(self._release)
        os.close(self._release)
        os.waitpid(self._child, 0)


def _connects_and_closes_as(uid: int, port: int, count: int) -> int:
    """Open and close `count` connections as `uid`, as fast as it can; return how many opened."""
    reader, writer = os.pipe()
    child = os.fork()
    if child == 0:
        opened = 0
        try:
            os.setgroups([])
            os.setresgid(uid, uid, uid)
            os.setresuid(uid, uid, uid)
            for _ in range(count):
                connection = socket.socket()
                connection.settimeout(3)
                try:
                    connection.connect(("127.0.0.1", port))
                    opened += 1
                except OSError:
                    pass
                finally:
                    connection.close()
        finally:
            os.write(writer, str(opened).encode())
            os._exit(0)
    os.close(writer)
    with os.fdopen(reader) as result:
        opened = int(result.read() or "0")
    os.waitpid(child, 0)
    return opened


def _close_accepted(listener: socket.socket) -> None:
    """Accept and close what is queued, as PostgreSQL closes a connection its client left."""
    listener.setblocking(False)
    while True:
        try:
            connection, _ = listener.accept()
        except BlockingIOError:
            return
        connection.close()


def _caps_in_a_fresh_network_namespace(database_cap: int) -> dict:
    """Install the caps in a namespace of its own (never the host's) and try them there."""
    _bring_up_loopback()
    install_connection_limits(UIDS, database_cap)
    database_listener = socket.socket()
    database_listener.bind(("127.0.0.1", PLUGINS_DB_PORT))
    database_listener.listen(256)
    proxy_listener = socket.socket()
    proxy_listener.bind(("127.0.0.1", network_limits.EGRESS_PROXY_PORT))
    proxy_listener.listen(256)

    flooding = _HeldConnections(20001, PLUGINS_DB_PORT, database_cap + 5)
    other_plugin = _HeldConnections(20002, PLUGINS_DB_PORT, database_cap)
    agent = _HeldConnections(AGENT_UID, PLUGINS_DB_PORT, database_cap + 5)
    proxy = _HeldConnections(20003, network_limits.EGRESS_PROXY_PORT, PROXY_CONNECTIONS_PER_PLUGIN + 6)
    outcome = {
        "plugin_to_database": flooding.opened,
        "another_plugin_meanwhile": other_plugin.opened,
        "agent_to_database": agent.opened,
        "plugin_to_proxy": proxy.opened,
    }
    for held in (flooding, other_plugin, agent, proxy):
        held.release()
    time.sleep(0.2)
    _close_accepted(database_listener)
    time.sleep(0.2)
    again = _HeldConnections(20001, PLUGINS_DB_PORT, database_cap)
    outcome["plugin_again_after_closing"] = again.opened
    again.release()

    # A flood of new connections, to a port no cap counts.
    service = socket.socket()
    service.bind(("127.0.0.1", 8080))
    service.listen(4096)
    flood_size = (NEW_CONNECTIONS_BURST + NEW_CONNECTIONS_PER_SECOND) * 3
    outcome["flood_opened_fewer_than_sent"] = _connects_and_closes_as(20004, 8080, flood_size) < flood_size
    _close_accepted(service)
    outcome["another_plugin_during_the_flood"] = _connects_and_closes_as(20005, 8080, 20)
    outcome["agent_during_the_flood"] = _connects_and_closes_as(AGENT_UID, 8080, flood_size)
    return outcome


@pytest.mark.root
@pytest.mark.skipif(shutil.which("nft") is None, reason="needs nftables (nft)")
def test_the_kernel_holds_each_plugin_uid_to_its_caps_and_leaves_the_agent_alone():
    reader, writer = os.pipe()
    child = os.fork()
    if child == 0:
        outcome: dict = {}
        try:
            os.unshare(os.CLONE_NEWNET)
            outcome = _caps_in_a_fresh_network_namespace(database_cap=3)
        except BaseException as error:
            outcome = {"error": f"{type(error).__name__}: {error}"}
        finally:
            os.write(writer, json.dumps(outcome).encode())
            os._exit(0)
    os.close(writer)
    with os.fdopen(reader) as result:
        outcome = json.loads(result.read())
    os.waitpid(child, 0)

    flood_size = (NEW_CONNECTIONS_BURST + NEW_CONNECTIONS_PER_SECOND) * 3
    assert outcome == {
        "plugin_to_database": 3,
        "another_plugin_meanwhile": 3,
        "agent_to_database": 8,
        "plugin_again_after_closing": 3,
        "plugin_to_proxy": PROXY_CONNECTIONS_PER_PLUGIN,
        "flood_opened_fewer_than_sent": True,
        "another_plugin_during_the_flood": 20,
        "agent_during_the_flood": flood_size,
    }
