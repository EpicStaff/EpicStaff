"""Host allow-list / SSRF guard for outbound Git-provider calls.

Every URL a tool call wants to send a caller token to must pass
:func:`assert_url_allowed` first. Two independent checks are applied:

1. The URL base must appear in the operator-configured allow-list
   (``GIT_TOOLS_ALLOWED_URLS`` in the service ``.env``).
2. The resolved host must not be a private, loopback, link-local or otherwise
   internal address (blocks ``169.254.169.254`` and friends), unless the
   operator explicitly opts in via ``GIT_TOOLS_ALLOW_PRIVATE_HOSTS``.
"""

import ipaddress
import os
import socket
from dataclasses import dataclass
from typing import Iterable, Tuple
from urllib.parse import urlsplit

ALLOWED_URLS_ENV = "GIT_TOOLS_ALLOWED_URLS"
ALLOW_PRIVATE_HOSTS_ENV = "GIT_TOOLS_ALLOW_PRIVATE_HOSTS"

DEFAULT_ALLOWED_URLS = "https://gitlab.com,https://github.com,https://api.github.com"

DEFAULT_PORTS = {"http": 80, "https": 443}


class UrlNotAllowedError(ValueError):
    """Raised when a URL is outside the configured allow-list or resolves internally."""


@dataclass(frozen=True)
class AllowedUrl:
    scheme: str
    host: str
    port: int
    path_prefix: str

    @classmethod
    def parse(cls, raw: str) -> "AllowedUrl":
        parts = urlsplit(raw.strip())
        if parts.scheme not in DEFAULT_PORTS:
            raise UrlNotAllowedError(
                f"Allow-list entry {raw!r} must use http or https scheme"
            )
        if not parts.hostname:
            raise UrlNotAllowedError(f"Allow-list entry {raw!r} has no host")
        return cls(
            scheme=parts.scheme,
            host=parts.hostname.lower().rstrip("."),
            port=parts.port or DEFAULT_PORTS[parts.scheme],
            path_prefix=parts.path.rstrip("/"),
        )

    def matches(self, scheme: str, host: str, port: int, path: str) -> bool:
        if scheme != self.scheme or port != self.port:
            return False
        if not self._host_matches(host):
            return False
        if not self.path_prefix:
            return True
        return path == self.path_prefix or path.startswith(self.path_prefix + "/")

    def _host_matches(self, host: str) -> bool:
        if self.host.startswith("*."):
            return host == self.host[2:] or host.endswith(self.host[1:])
        return host == self.host


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_allowlist() -> Tuple[AllowedUrl, ...]:
    raw = os.getenv(ALLOWED_URLS_ENV)
    if raw is None:
        raw = DEFAULT_ALLOWED_URLS
    entries = tuple(AllowedUrl.parse(item) for item in raw.split(",") if item.strip())
    if not entries:
        raise UrlNotAllowedError(
            f"{ALLOWED_URLS_ENV} is empty - no Git host is allowed, refusing to send token"
        )
    return entries


def _resolved_addresses(host: str, port: int) -> Iterable[ipaddress._BaseAddress]:
    try:
        return {
            ipaddress.ip_address(info[4][0])
            for info in socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        }
    except socket.gaierror as exc:
        raise UrlNotAllowedError(f"Cannot resolve host {host!r}: {exc}") from exc


def _assert_public_host(host: str, port: int) -> None:
    for address in _resolved_addresses(host, port):
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            raise UrlNotAllowedError(
                f"Host {host!r} resolves to internal address {address} - blocked. "
                f"Set {ALLOW_PRIVATE_HOSTS_ENV}=true only for trusted self-hosted instances."
            )


def assert_url_allowed(url: str) -> str:
    """Return the normalized URL, or raise :class:`UrlNotAllowedError`."""
    if not url or not url.strip():
        raise UrlNotAllowedError("Empty URL is not allowed")

    parts = urlsplit(url.strip())
    if parts.scheme not in DEFAULT_PORTS:
        raise UrlNotAllowedError(f"Unsupported scheme in {url!r}: only http/https")
    if not parts.hostname:
        raise UrlNotAllowedError(f"URL {url!r} has no host")
    if parts.username or parts.password:
        raise UrlNotAllowedError("Credentials embedded in the URL are not allowed")

    host = parts.hostname.lower().rstrip(".")
    port = parts.port or DEFAULT_PORTS[parts.scheme]
    path = parts.path.rstrip("/")

    allowlist = load_allowlist()
    if not any(entry.matches(parts.scheme, host, port, path) for entry in allowlist):
        allowed = ", ".join(
            f"{e.scheme}://{e.host}:{e.port}{e.path_prefix}" for e in allowlist
        )
        raise UrlNotAllowedError(
            f"URL {url!r} is not in {ALLOWED_URLS_ENV}. Allowed bases: {allowed}"
        )

    if not _env_flag(ALLOW_PRIVATE_HOSTS_ENV):
        _assert_public_host(host, port)

    netloc = host if port == DEFAULT_PORTS[parts.scheme] else f"{host}:{port}"
    return f"{parts.scheme}://{netloc}{path}"
