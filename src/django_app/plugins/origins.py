"""Where EpicStaff and each plugin are served, as browsers name those origins."""

from urllib.parse import urlsplit

from django.conf import settings

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
