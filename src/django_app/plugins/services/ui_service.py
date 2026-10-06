"""Opening a plugin's own page, and serving its files to the sandboxed frame."""

import posixpath
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from rbac.access.resolver import PermissionResolver
from rbac.exceptions import OrgMembershipRequiredError
from rbac.models.enums import Permission, ResourceType
from tables.services.storage_service.path_utils import sanitize_storage_path

from plugins.exceptions import PluginHasNoUiError, PluginNotReadyError, PluginSuspendedError
from plugins.manifest import UI_CONTENT_TYPES
from plugins.models import Plugin, PluginAsset
from plugins.services import knowledge_service, ui_token
from plugins.services.presenter import PluginPresenter

UI_URL_PREFIX = "/api/plugin-ui/"


@dataclass(frozen=True)
class ServedAsset:
    content: bytes
    content_type: str


class PluginUiService:
    """Hand out page tokens and resolve the files a token may load."""

    def open_session(self, plugin: Plugin, *, user) -> dict:
        """A page URL for `user`, carrying a token valid for `ui_token.MAX_AGE_SECONDS`.

        The caller has already checked `plugins:use` in the plugin's org.

        Raises:
            PluginSuspendedError, PluginNotReadyError, PluginHasNoUiError: the page
                cannot open now.
        """
        knowledge_service.refresh_states([plugin])
        if plugin.suspended:
            raise PluginSuspendedError(plugin.name)
        if not plugin.ui_entry:
            raise PluginHasNoUiError()
        if plugin.state != Plugin.State.READY:
            raise PluginNotReadyError()

        token = ui_token.issue(
            ui_token.UiTokenClaims(plugin_pk=plugin.pk, org_id=plugin.org_id, user_id=user.pk)
        )
        presented = PluginPresenter().present(plugin)
        return {
            "url": f"{UI_URL_PREFIX}{token}/{plugin.ui_entry}",
            "token": token,
            "expires_in": ui_token.MAX_AGE_SECONDS,
            "bridge_version": plugin.bridge_version,
            "plugin": {
                "id": plugin.pk,
                "plugin_id": plugin.plugin_id,
                "name": plugin.name,
                "version": plugin.version,
            },
            "access": [
                {key: entry[key] for key in ("alias", "type", "actions", "resource_id")}
                for entry in presented["access"]
            ],
        }

    def find_asset(self, token: str, path: str) -> ServedAsset | None:
        """The file `path` of the token's plugin, or None when anything is off.

        Re-checked on every request, because the token outlives the state it was
        issued in: the signature and age, the plugin still existing in the token's
        org, ready and not suspended, the token's user still holding
        `plugins:use` there, and the path being a canonical path of one of the
        plugin's own files with an allowed type.
        """
        claims = ui_token.read(token)
        if claims is None:
            return None
        content_type = _content_type(path)
        if content_type is None:
            return None
        plugin = Plugin.objects.filter(pk=claims.plugin_pk, org_id=claims.org_id).first()
        if plugin is None or plugin.suspended or not plugin.ui_entry:
            return None
        # Before refresh_states, which may write: nothing changes for a caller who
        # may no longer use the plugin.
        if not _may_use(claims.user_id, plugin.org_id):
            return None
        knowledge_service.refresh_states([plugin])
        if plugin.state != Plugin.State.READY:
            return None
        asset = PluginAsset.objects.filter(plugin=plugin, path=path).only("content").first()
        if asset is None:
            return None
        return ServedAsset(content=bytes(asset.content), content_type=content_type)


def _content_type(path: str) -> str | None:
    """The served type of a canonical asset path; None for any other path."""
    try:
        canonical = sanitize_storage_path(path, allow_empty=False)
    except ValueError:
        return None
    # A path that normalising changes ("a/../b", "./b", "a//b", a backslash) is
    # refused rather than rewritten, so one asset has exactly one URL.
    if canonical != path:
        return None
    return UI_CONTENT_TYPES.get(posixpath.splitext(path)[1].lower())


def _may_use(user_id: int, org_id: int) -> bool:
    user = get_user_model().objects.filter(pk=user_id, is_active=True).first()
    if user is None:
        return False
    try:
        effective = PermissionResolver().resolve(user=user, org_id=org_id)
    except OrgMembershipRequiredError:
        return False
    return effective.can(ResourceType.PLUGINS, Permission.USE)
