"""Every port of the node's range, bound by the agent at start-up and held for its whole life.

A plugin process never binds its port: the agent hands it the listening socket of its
placement's port at spawn (see `ProcessSupervisor`). Holding *every* port of the range, assigned
or not, leaves a plugin no port of the range to take: not another plugin's, and not one a later
placement will be given, which it could otherwise bind without listening (such a socket shows
nowhere in `/proc/net/tcp`) and so keep the agent from ever binding it.

The sockets are bound with `SO_REUSEADDR`. A connection the plugin closed first leaves a
TIME_WAIT on its port for a minute, which takes the listener's `SO_REUSEADDR` with it; without
the option on both, the fresh socket below could not be bound until it expired. The option lets
another socket that carries it share a port that is not listening, but nothing else on the node
can: no plugin may `bind()` at all (`bind_refusal`), and the kernel picks a port by itself only
from the ephemeral range, 21000-65535, above the node's range. A listening port refuses every
other bind. A port listens only while a placement uses it: one given back refuses connections
again. The agent starts once per container (a restart is a new network namespace), so nothing
of an earlier run holds a port.

A plugin process shares its port's socket, as its fd 3, and may change it: shut it down and
connect it somewhere, say. It may also pass a copy to another plugin over a UNIX socket, which
every plugin on the node can reach. So a socket that served one placement never serves the
next: a port given back has its socket shut down, which stops it listening for every holder,
closed with a reset rather than a wait, and replaced by a fresh one. Once the fresh socket
listens, a copy of the old one can no longer listen. Between the give-back and the next `take`
the fresh socket is only bound, so a holder of a copy may listen on it first: `take` then
cannot listen and refuses the port (`PortUnavailableError`, retried) until the copy is closed.
Nothing is routed to a placement that has not started, and a connection the holder accepts
stops it (`socket_watchdog`). A socket found changed when its port is taken is replaced the same
way.
"""

import contextlib
import errno
import socket
import struct
from collections.abc import Iterable

from loguru import logger

LISTEN_BACKLOG = 128
# SO_LINGER on, 0 s: closing sends a reset, and the port is free again at once.
_RESET_ON_CLOSE = struct.pack("ii", 1, 0)


class PortReservationError(Exception):
    """The agent could not bind a port of the node's range at start-up; it does not start."""


class PortUnavailableError(Exception):
    """A placement's port is not one the agent holds for it (retried)."""


class PortReservation:
    def __init__(self, ports: Iterable[int]):
        self._ports = sorted(set(ports))
        self._reserved = frozenset(self._ports)
        # A port of the range is missing here only while a fresh socket could not be bound.
        self._sockets: dict[int, socket.socket] = {}
        self._users: dict[int, int] = {}

    def reserve(self) -> None:
        """Bind every port. Python's sockets are not inherited, so no plugin gets one by accident.

        Raises:
            PortReservationError: A port could not be bound (or the agent ran out of
                descriptors); every socket bound so far is closed again.
        """
        for port in self._ports:
            try:
                self._sockets[port] = _bound(port)
            except OSError as error:
                self.close()
                raise PortReservationError(
                    f"port {port} of the node's range could not be bound: {error}"
                ) from None

    def take(self, port: int, placement_id: int) -> int:
        """Start listening on `port` for `placement_id`; return the descriptor to spawn with.

        Taking the same port again for the same placement returns the same descriptor, unless
        its socket had to be replaced.

        Raises:
            PortUnavailableError: The port is not one of the node's, another placement still
                uses it, or its socket had to be replaced and the port cannot be bound now.
        """
        if port not in self._reserved:
            raise PortUnavailableError(f"port {port} is not one of this node's ports")
        user = self._users.get(port)
        if user is not None and user != placement_id:
            raise PortUnavailableError(f"port {port} is still in use by placement {user}")
        held = self._intact(port)
        try:
            held.listen(LISTEN_BACKLOG)
        except OSError as error:
            if error.errno == errno.EADDRINUSE:
                # A fresh socket would be refused the same way: wait for the other to close.
                raise _cannot_listen(port, error) from None
            # In no state to listen, e.g. a connection to somewhere still under way.
            held = self._replace(port, f"it could not listen: {error}")
            try:
                held.listen(LISTEN_BACKLOG)
            except OSError as again:
                raise _cannot_listen(port, again) from None
        self._users[port] = placement_id
        return held.fileno()

    def give_back(self, port: int, placement_id: int) -> None:
        """`placement_id` no longer uses `port`: replace its socket, and keep holding the port.

        On Linux, `shutdown` of a listening socket stops it listening and resets the connections
        still queued, through every descriptor of it, so none reaches the next plugin given the
        port. When the fresh socket cannot be bound, another socket listens on the port: the
        port stays unusable, `take` refusing it until it can be bound, and a warning says so.
        """
        if self._users.get(port) != placement_id:
            return
        del self._users[port]
        held = self._sockets.get(port)
        changed = held is not None and not _holds_its_port(held, port)
        try:
            self._replace(port, "it is no longer bound to its port alone" if changed else None)
        except PortUnavailableError as error:
            logger.warning("plugins.port.rebind_failed port={} error={}", port, error)

    @property
    def reserved_ports(self) -> frozenset[int]:
        """Every port of the node's range, held by the agent whether a placement uses it or not."""
        return self._reserved

    def close(self) -> None:
        for held in self._sockets.values():
            held.close()
        self._sockets.clear()
        self._users.clear()

    def _intact(self, port: int) -> socket.socket:
        held = self._sockets.get(port)
        if held is not None and _holds_its_port(held, port):
            return held
        return self._replace(port, "it is no longer bound to its port alone")

    def _replace(self, port: int, reason: str | None) -> socket.socket:
        """Shut the port's socket down and close it, if there is one, and bind a fresh one.

        Args:
            reason: Why a socket found changed is replaced, logged as a warning; None for one
                replaced only because its port was given back.

        Raises:
            PortUnavailableError: The port cannot be bound now: another socket listens on it.
        """
        old = self._sockets.pop(port, None)
        if old is not None:
            if reason is not None:
                logger.warning("plugins.port.replaced port={} reason={}", port, reason)
            # Either may fail, e.g. shutdown of a socket that never listened: it is closed all
            # the same.
            with contextlib.suppress(OSError):
                old.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, _RESET_ON_CLOSE)
            with contextlib.suppress(OSError):
                old.shutdown(socket.SHUT_RDWR)
            old.close()
        try:
            fresh = _bound(port)
        except OSError as error:
            raise PortUnavailableError(f"port {port} could not be bound again: {error}") from None
        self._sockets[port] = fresh
        return fresh


def _cannot_listen(port: int, error: OSError) -> PortUnavailableError:
    if error.errno != errno.EADDRINUSE:
        return PortUnavailableError(f"port {port} cannot listen: {error}")
    return PortUnavailableError(
        f"port {port} cannot listen: another socket listens on it, a copy of the socket of the "
        "placement that had it before; it is taken once that copy is closed"
    )


def _bound(port: int) -> socket.socket:
    held = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        held.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        held.bind(("0.0.0.0", port))
    except OSError:
        held.close()
        raise
    return held


def _holds_its_port(held: socket.socket, port: int) -> bool:
    """Whether `held` is still bound to `0.0.0.0:<port>` and connected to nothing."""
    try:
        if held.getsockname() != ("0.0.0.0", port):
            return False
        held.getpeername()
    except OSError as error:
        return error.errno == errno.ENOTCONN
    return False
