"""The per-plugin socket watchdog: no listening socket of its own, and a bounded number of inet
sockets, checked every second.

A plugin cannot `bind()` an inet socket (`bind_refusal`), but the kernel binds a port by itself,
without that hook, for `listen()` on an unbound TCP socket, and for a UDP `connect()`. Such a
socket holds one of the namespace's ephemeral ports (21000-65535, shared by every plugin and the
agent) for as long as it is open, and the connection limits never count it. A plugin may hold
256 descriptors per process and 64 processes, so a few plugins could take every port and leave
the agent unable to reach django_app or plugins_db.

Every second the watchdog reads `/proc/net/{tcp,tcp6,udp,udp6}` of the node's network namespace,
which the plugins share with the agent, and counts each running plugin's sockets by the `uid`
column. A plugin breaches when its UID owns a TCP socket in LISTEN, or more than
`MAX_INET_SOCKETS` inet sockets in all. The socket a plugin serves on is not its own: the agent
made it (`PortReservation`), so it is listed under the agent's UID, and so is every connection
it accepts. A breach kills the plugin's UID and leaves the plugin `failed` with the reason in
the node's report (`ProcessSupervisor.fail_for`), until EpicStaff restarts it or installs another
version: a restart with backoff, as for memory, would only take the ports again. Between two
checks a plugin can still take ports for up to a second.

The work per check is bounded: each table is read up to `MAX_LINES_PER_TABLE` lines, in a thread,
a line that does not parse is skipped, and a table that cannot be read is logged (once until it
can be read again) and left out of that check. The watchdog never stops on an error of its own.
Log line: `plugins.socket_watchdog.stopped`.
"""

import asyncio
import itertools
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from es_plugins.supervisor.process_supervisor import ProcessSupervisor

POLL_INTERVAL_SECONDS = 1.0
# Far above what a plugin's process uses (its database pool, its proxy connections, name
# lookups), far below what exhausts the namespace's ephemeral ports.
MAX_INET_SOCKETS = 512
# Every port of the namespace's range, twice over: a table longer than this is cut, and a plugin
# that fills it is past its cap long before.
MAX_LINES_PER_TABLE = 100_000
PROC_NET = Path("/proc/net")
# `st` of a TCP socket in LISTEN (include/net/tcp_states.h).
TCP_LISTEN = 0x0A
_TABLES = (("tcp", True), ("tcp6", True), ("udp", False), ("udp6", False))


@dataclass(frozen=True)
class SocketEntry:
    """One row of a `/proc/net` socket table: what the watchdog reads of it."""

    local_port: int
    state: int
    uid: int


def parse_socket_line(line: str) -> SocketEntry | None:
    """A row of `/proc/net/{tcp,tcp6,udp,udp6}`, or None when it is not one.

    `sl local_address rem_address st tx_queue:rx_queue tr:tm->when retrnsmt uid timeout inode
    ...`, the addresses as `<hex address>:<hex port>`.
    """
    fields = line.split()
    if len(fields) < 10 or not fields[0].endswith(":"):
        return None
    try:
        _, separator, port = fields[1].rpartition(":")
        if not separator:
            return None
        return SocketEntry(local_port=int(port, 16), state=int(fields[3], 16), uid=int(fields[7]))
    except ValueError:
        return None


@dataclass
class SocketUse:
    """Each watched UID's inet sockets, and a TCP port it listens on (the first found)."""

    sockets: Counter = field(default_factory=Counter)
    listening: dict[int, int] = field(default_factory=dict)


class SocketTables:
    """Reads the namespace's socket tables, logging a table it cannot read once until it can."""

    def __init__(self, root: Path = PROC_NET):
        self._root = root
        self._unreadable: set[str] = set()

    def use_of(self, uids: set[int]) -> SocketUse:
        """The socket use of `uids`, from every table that can be read now."""
        use = SocketUse()
        for name, is_tcp in _TABLES:
            try:
                with open(self._root / name, encoding="ascii", errors="replace") as table:
                    # The first line is the header.
                    for line in itertools.islice(table, 1, MAX_LINES_PER_TABLE + 1):
                        entry = parse_socket_line(line)
                        if entry is None or entry.uid not in uids:
                            continue
                        use.sockets[entry.uid] += 1
                        if is_tcp and entry.state == TCP_LISTEN:
                            use.listening.setdefault(entry.uid, entry.local_port)
            except OSError as error:
                if name not in self._unreadable:
                    self._unreadable.add(name)
                    logger.warning("The socket watchdog cannot read {}: {}", name, error)
                continue
            self._unreadable.discard(name)
        return use


class SocketWatchdog:
    def __init__(
        self,
        supervisors: Callable[[], Iterable[ProcessSupervisor]],
        *,
        tables: SocketTables | None = None,
        interval: float = POLL_INTERVAL_SECONDS,
    ):
        self._supervisors = supervisors
        self._tables = tables or SocketTables()
        self._interval = interval

    async def check_once(self) -> list[ProcessSupervisor]:
        """Stop every running plugin whose UID listens on a port of its own or holds more than
        `MAX_INET_SOCKETS` inet sockets.

        Returns:
            The supervisors stopped by this check.
        """
        watched = {
            supervisor.uid: supervisor for supervisor in self._supervisors() if supervisor.watching
        }
        if not watched:
            return []
        use = await asyncio.to_thread(self._tables.use_of, set(watched))
        stopped = []
        for uid, supervisor in watched.items():
            reason = _breach(use, uid)
            if reason is None or not supervisor.watching:
                continue
            logger.error(
                "plugins.socket_watchdog.stopped plugin={} uid={} listening_port={} sockets={}",
                supervisor.plugin,
                uid,
                use.listening.get(uid, "none"),
                use.sockets[uid],
            )
            supervisor.fail_for(reason)
            stopped.append(supervisor)
        return stopped

    async def run(self) -> None:
        while True:
            try:
                await self.check_once()
            except Exception:
                # The node stops when a watchdog ends: one check's error must not end this one.
                logger.exception("The socket watchdog's check failed")
            await asyncio.sleep(self._interval)


def _breach(use: SocketUse, uid: int) -> str | None:
    """Why the UID's sockets break the rules, as the plugin's report says it; None when not."""
    port = use.listening.get(uid)
    if port is not None:
        return (
            f"it listened on TCP port {port} of its own; a plugin serves only on the socket the "
            "node hands it, so it stays stopped until it is restarted"
        )
    count = use.sockets[uid]
    if count > MAX_INET_SOCKETS:
        return (
            f"it held {count} network sockets, more than the {MAX_INET_SOCKETS} a plugin may; "
            "it stays stopped until it is restarted"
        )
    return None
