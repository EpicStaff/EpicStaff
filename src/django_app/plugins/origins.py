"""Where EpicStaff and each plugin are served, as browsers name those origins."""

import re
from urllib.parse import urlsplit

from django.conf import settings
from epicstaff_plugin.contracts.manifest import IDENTIFIER_PATTERN

_DEFAULT_PORTS = {"http": 80, "https": 443}


class PluginOrigins:
    """Origins built from `DJANGO_FRONTEND_BASE_URL` and `PLUGINS_BASE_DOMAIN`.

    A plugin is served at `<identifier>.<PLUGINS_BASE_DOMAIN>` with EpicStaff's scheme and
    explicit port. A default port is left out, as browsers leave it out of `event.origin`.
    The start-up checks (plugins.E002, plugins.E003) guarantee both settings are well formed
    while the platform is on.
    """

    def __init__(self, frontend_base_url: str | None = None, base_domain: str | None = None):
        parts = urlsplit(frontend_base_url or settings.FRONTEND_BASE_URL)
        self._scheme = parts.scheme
        self._host = parts.hostname or ""
        self._port_suffix = (
            f":{parts.port}"
            if parts.port and parts.port != _DEFAULT_PORTS.get(parts.scheme)
            else ""
        )
        self._base_domain = base_domain or settings.PLUGINS_BASE_DOMAIN

    @property
    def epicstaff_origin(self) -> str:
        return f"{self._scheme}://{self._host}{self._port_suffix}"

    def plugin_host(self, identifier: str) -> str:
        return f"{identifier}.{self._base_domain}"

    def frame_origin(self, identifier: str) -> str:
        return f"{self._scheme}://{self.plugin_host(identifier)}{self._port_suffix}"

    def identifier_from_origin(self, origin: str) -> str | None:
        """Return the plugin whose frame origin `origin` is, exactly; otherwise None.

        Only one label in front of the base domain counts, and only one the manifest allows as
        an identifier. The scheme and port must be EpicStaff's own, so an `http://` origin is
        no plugin's on an HTTPS deployment, and case must match as browsers serialize it.
        """
        prefix = f"{self._scheme}://"
        suffix = f".{self._base_domain}{self._port_suffix}"
        if not origin.startswith(prefix) or not origin.endswith(suffix):
            return None
        label = origin[len(prefix) : -len(suffix)]
        if re.fullmatch(IDENTIFIER_PATTERN, label) is None:
            return None
        return label

    def is_plugin_domain_origin(self, origin: str) -> bool:
        """Whether `origin`'s host is the plugin base domain or under it, for any scheme and port.

        Wider than `identifier_from_origin` on purpose: it decides which requests the Origin
        policy judges at all, so a nested label, the base domain itself or a host spelt with a
        trailing dot is judged (and refused) rather than let through as a stranger. `null` and
        origins that do not parse have no host and are not plugin-domain origins.
        """
        try:
            host = urlsplit(origin).hostname
        except ValueError:
            return False
        if not host:
            return False
        host = host.rstrip(".")
        return host == self._base_domain or host.endswith(f".{self._base_domain}")
