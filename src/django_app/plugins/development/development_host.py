"""The one host plugin development mode routes to: the machine Docker runs on.

The SuperAdmin enters only ports; the name is fixed, so development mode can never send a
plugin's traffic to another host or service. Django resolves it and hands nginx an address,
because nginx's runtime resolver does not read Docker's `extra_hosts`: on Linux the name
exists only through `extra_hosts` (`docker-compose.plugins-dev.yaml`), while Docker Desktop
has it built in.
"""

import socket
import threading
import time
from collections.abc import Callable

from plugins.audit import log_development_host_unresolved

# A success and a failure are both kept this long, so a failure is looked up, and logged, at
# most once a minute per process.
ADDRESS_CACHE_SECONDS = 60

Resolver = Callable[..., list]


class DevelopmentHost:
    NAME = "host.docker.internal"

    def __init__(
        self,
        resolver: Resolver = socket.getaddrinfo,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._resolver = resolver
        self._clock = clock
        self._lock = threading.Lock()
        self._cached: tuple[float, str | None] | None = None

    def address(self) -> str | None:
        """The first IPv4 address `NAME` resolves to in this process, or None.

        Resolved at most once per `ADDRESS_CACHE_SECONDS`, under a lock, so concurrent gateway
        checks never look it up twice. Only `NAME` is ever resolved.
        """
        with self._lock:
            now = self._clock()
            if self._cached is not None and now - self._cached[0] < ADDRESS_CACHE_SECONDS:
                return self._cached[1]
            address = self._resolve()
            self._cached = (now, address)
        if address is None:
            log_development_host_unresolved(self.NAME)
        return address

    def forget(self) -> None:
        """Drop the cached answer, so the next call resolves the name again."""
        with self._lock:
            self._cached = None

    def _resolve(self) -> str | None:
        try:
            entries = self._resolver(self.NAME, None, socket.AF_INET, socket.SOCK_STREAM)
        except (OSError, UnicodeError):
            return None
        for family, _type, _protocol, _name, socket_address in entries:
            if family == socket.AF_INET:
                return socket_address[0]
        return None


development_host = DevelopmentHost()
