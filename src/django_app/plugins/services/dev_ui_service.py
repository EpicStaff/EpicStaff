"""Plugin dev mode: an installed plugin's page loaded from its author's dev server.

The page then comes from `http://localhost:<port>/...` with live reload, but still
runs in the same sandboxed frame and talks to EpicStaff only through the bridge, as
the admin who opened it. It exists only while the instance runs with
settings.PLUGINS_DEV_MODE on, and only for the admin who set the URL: everyone else
keeps getting the installed files.
"""

import re

from django.conf import settings

from plugins.exceptions import InvalidPluginDevUiUrlError, PluginDevModeDisabledError
from plugins.models import Plugin

# Plain http on the loopback host only: no userinfo, query or fragment. `[0-9]`, not
# `\d`, which also matches non-ASCII digits that int() would then accept.
DEV_UI_URL_PATTERN = re.compile(
    r"http://(?:localhost|127\.0\.0\.1)(?::(?P<port>[0-9]{1,5}))?(?:/[A-Za-z0-9._~/%-]*)?"
)
MAX_DEV_UI_URL_LENGTH = 255


def validate_dev_ui_url(url: str) -> None:
    """Raises: InvalidPluginDevUiUrlError: `url` is not an acceptable dev server URL."""
    match = DEV_UI_URL_PATTERN.fullmatch(url) if len(url) <= MAX_DEV_UI_URL_LENGTH else None
    if match is None:
        raise InvalidPluginDevUiUrlError()
    port = match.group("port")
    if port is not None and not 0 < int(port) <= 65535:
        raise InvalidPluginDevUiUrlError()


class PluginDevUiService:
    """Point a plugin's page at a localhost dev server for one admin, and stop again."""

    def require_enabled(self) -> None:
        """Raises: PluginDevModeDisabledError: the instance does not run in plugin dev mode."""
        if not settings.PLUGINS_DEV_MODE:
            raise PluginDevModeDisabledError()

    def set_url(self, plugin: Plugin, url: str, *, user) -> Plugin:
        """Load `plugin`'s page from `url` for `user` only, replacing any earlier dev URL.

        Raises:
            PluginDevModeDisabledError: the instance does not run in plugin dev mode.
            InvalidPluginDevUiUrlError: `url` is not a plain http URL on localhost.
        """
        self.require_enabled()
        validate_dev_ui_url(url)
        plugin.dev_ui_url = url
        plugin.dev_ui_user = user
        plugin.save(update_fields=["dev_ui_url", "dev_ui_user", "updated_at"])
        return plugin

    def clear(self, plugin: Plugin) -> Plugin:
        """Serve the installed page to everyone again.

        Allowed with dev mode off too, so a URL left over from a dev session can be removed.
        """
        plugin.dev_ui_url = ""
        plugin.dev_ui_user = None
        plugin.save(update_fields=["dev_ui_url", "dev_ui_user", "updated_at"])
        return plugin

    def dev_url_for(self, plugin: Plugin, user) -> str | None:
        """The dev server URL `user` should load `plugin`'s page from, or None for the installed page."""
        if settings.PLUGINS_DEV_MODE and plugin.dev_ui_url and plugin.dev_ui_user_id == user.pk:
            return plugin.dev_ui_url
        return None
