"""Where EpicStaff and each plugin are served, as browsers name those origins."""

import re
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from epicstaff_plugin.contracts.manifest import IDENTIFIER_PATTERN

from plugins.configuration.host_template import InvalidHostTemplateError, PluginHostTemplate

_DEFAULT_PORTS = {"http": 80, "https": 443}


class PluginOrigins:
    """Origins built from `DJANGO_FRONTEND_BASE_URL` and `PLUGINS_HOST_TEMPLATE`.

    A plugin is served at the template's host for its identifier, with EpicStaff's scheme and
    explicit port. A default port is left out, as browsers leave it out of `event.origin`.
    The start-up checks (plugins.E002, plugins.E003) guarantee both settings are well formed
    while the platform is on.

    Raises:
        ImproperlyConfigured: The template is not a valid one; only possible while the
            platform is off, when nothing should build plugin origins.
    """

    def __init__(self, frontend_base_url: str | None = None, host_template: str | None = None):
        parts = urlsplit(frontend_base_url or settings.FRONTEND_BASE_URL)
        self._scheme = parts.scheme
        self._host = parts.hostname or ""
        self._port_suffix = (
            f":{parts.port}"
            if parts.port and parts.port != _DEFAULT_PORTS.get(parts.scheme)
            else ""
        )
        template = host_template or settings.PLUGINS_HOST_TEMPLATE
        try:
            self._template = PluginHostTemplate.parse(template)
        except InvalidHostTemplateError as error:
            raise ImproperlyConfigured(f"PLUGINS_HOST_TEMPLATE ({template!r}): {error}.") from error

    @property
    def epicstaff_origin(self) -> str:
        return f"{self._scheme}://{self._host}{self._port_suffix}"

    @property
    def host_template(self) -> PluginHostTemplate:
        return self._template

    def plugin_host(self, identifier: str) -> str:
        return self._template.host(identifier)

    def frame_origin(self, identifier: str) -> str:
        return f"{self._scheme}://{self.plugin_host(identifier)}{self._port_suffix}"

    def identifier_from_origin(self, origin: str) -> str | None:
        """Return the plugin whose frame origin `origin` is, exactly; otherwise None.

        Only one label in front of the parent counts: the template's prefix and suffix around
        an identifier the manifest allows. The scheme and port must be EpicStaff's own, so an
        `http://` origin is no plugin's on an HTTPS deployment, and case must match as browsers
        serialize it.
        """
        scheme = f"{self._scheme}://"
        parent = f".{self._template.parent}{self._port_suffix}"
        if not origin.startswith(scheme) or not origin.endswith(parent):
            return None
        label = origin[len(scheme) : -len(parent)]
        identifier = self._template.plugin_label_middle(label)
        if identifier is None or re.fullmatch(IDENTIFIER_PATTERN, identifier) is None:
            return None
        return identifier

    def is_plugin_zone_origin(self, origin: str) -> bool:
        """Whether `origin`'s host is in the plugin zone, for any scheme and port.

        Wider than `identifier_from_origin` on purpose: it decides which requests the Origin
        policy judges at all, so a nested label, a label of a plugin host's shape that names no
        valid identifier or a host spelt with a trailing dot is judged (and refused) rather
        than let through as a stranger. See `PluginHostTemplate.covers` for the zone. `null`
        and origins that do not parse have no host and are not plugin-zone origins.
        """
        try:
            host = urlsplit(origin).hostname
        except ValueError:
            return False
        return self._template.covers(host)
