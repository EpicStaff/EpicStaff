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
"""

import socket
from collections.abc import Iterable

LISTEN_BACKLOG = 128


class PortReservationError(Exception):
    """The agent could not bind a port of the node's range at start-up; it does not start."""


class PortUnavailableError(Exception):
    """A placement's port is not one the agent holds for it (retried)."""


class PortReservation:
    def __init__(self, ports: Iterable[int]):
        self._ports = sorted(set(ports))
        self._sockets: dict[int, socket.socket] = {}
        self._users: dict[int, int] = {}

    def reserve(self) -> None:
        """Bind every port. Python's sockets are not inherited, so no plugin gets one by accident.

        Raises:
            PortReservationError: A port could not be bound (or the agent ran out of
                descriptors); every socket bound so far is closed again.
        """
        for port in self._ports:
            held = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                held.bind(("0.0.0.0", port))
            except OSError as error:
                held.close()
                self.close()
                raise PortReservationError(
                    f"port {port} of the node's range could not be bound: {error}"
                ) from None
            self._sockets[port] = held

    def take(self, port: int, placement_id: int) -> int:
        """Start listening on `port` for `placement_id`; return the descriptor to spawn with.

        Taking the same port again for the same placement returns the same descriptor.

        Raises:
            PortUnavailableError: The port is not one of the node's, or another placement
                still uses it.
        """
        held = self._sockets.get(port)
        if held is None:
            raise PortUnavailableError(f"port {port} is not one of this node's ports")
        user = self._users.get(port)
        if user is not None and user != placement_id:
            raise PortUnavailableError(f"port {port} is still in use by placement {user}")
        held.listen(LISTEN_BACKLOG)
        self._users[port] = placement_id
        return held.fileno()

    def give_back(self, port: int, placement_id: int) -> None:
        """`placement_id` no longer uses `port`: stop listening on it, and keep holding it.

        On Linux, `shutdown` of a listening socket stops it listening and resets the connections
        still queued (none reaches the next plugin given the port), while the port stays bound to
        it, exclusively, and it can listen again.
        """
        if self._users.get(port) != placement_id:
            return
        del self._users[port]
        self._sockets[port].shutdown(socket.SHUT_RDWR)

    def close(self) -> None:
        for held in self._sockets.values():
            held.close()
        self._sockets.clear()
        self._users.clear()
