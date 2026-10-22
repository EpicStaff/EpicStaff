"""Every port of the node's range, bound by the agent at start-up and held for its whole life.

A plugin process never binds its port: the agent hands it the listening socket of its
placement's port at spawn (see `ProcessSupervisor`). Holding *every* port of the range, assigned
or not, leaves a plugin no port of the range to take: not another plugin's, and not one a later
placement will be given, which it could otherwise bind without listening (such a socket shows
nowhere in `/proc/net/tcp`) and so keep the agent from ever binding it.

The sockets are bound without `SO_REUSEADDR`, so no other socket can share a port with them,
listening or not. A port listens only while a placement uses it: one given back refuses
connections again. The agent starts once per container (a restart is a new network
namespace), so nothing of an earlier run holds a port.

A plugin process shares its port's socket, as its fd 3, and may change it: shut it down and
connect it somewhere, say. So each time a port is taken or given back, its socket is checked to
be what `reserve` made, bound to `0.0.0.0:<port>` and connected to nothing; one that is not is
closed, with a reset rather than a wait, and a fresh socket is bound in its place.
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
        except OSError:
            # In no state to listen, e.g. a connection to somewhere still under way.
            held = self._replace(port, "it could not listen")
            held.listen(LISTEN_BACKLOG)
        self._users[port] = placement_id
        return held.fileno()

    def give_back(self, port: int, placement_id: int) -> None:
        """`placement_id` no longer uses `port`: stop listening on it, and keep holding it.

        On Linux, `shutdown` of a listening socket stops it listening and resets the connections
        still queued (none reaches the next plugin given the port), while the port stays bound to
        it, exclusively, and it can listen again. A socket that is no longer bound to its port
        alone is replaced instead; if the port cannot be bound now, `take` tries again.
        """
        if self._users.get(port) != placement_id:
            return
        del self._users[port]
        held = self._sockets.get(port)
        if held is None:
            return
        if not _holds_its_port(held, port):
            try:
                self._replace(port, "it is no longer bound to its port alone")
            except PortUnavailableError as error:
                logger.warning("{}", error)
            return
        held.shutdown(socket.SHUT_RDWR)

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

    def _replace(self, port: int, reason: str) -> socket.socket:
        """Close the port's socket, if there is one, and bind a fresh one.

        Raises:
            PortUnavailableError: The port cannot be bound now, e.g. while a plugin process still
                holds the old socket.
        """
        old = self._sockets.pop(port, None)
        if old is not None:
            logger.warning("plugins.port.replaced port={} reason={}", port, reason)
            # A socket the kernel no longer takes options for is closed all the same.
            with contextlib.suppress(OSError):
                old.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, _RESET_ON_CLOSE)
            old.close()
        try:
            fresh = _bound(port)
        except OSError as error:
            raise PortUnavailableError(f"port {port} could not be bound again: {error}") from None
        self._sockets[port] = fresh
        return fresh


def _bound(port: int) -> socket.socket:
    held = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
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
