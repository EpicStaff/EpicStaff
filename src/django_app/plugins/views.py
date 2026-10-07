from rbac.access.action_map import DEFAULT_ACTION_MAP
from rbac.access.asserts import assert_org_permission
from rbac.access.gates import DenyApiKeyAuth, HasOrgPermission
from rbac.models.enums import Permission, ResourceType
from rbac.scoping.mixins import OrgScopedViewSetMixin
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from plugins.models import Plugin
from plugins.serializers import (
    PluginDevUiRequestSerializer,
    PluginInspectRequestSerializer,
    PluginInstallRequestSerializer,
    PluginSecretsRequestSerializer,
)
from plugins.services import knowledge_service
from plugins.services.dev_ui_service import PluginDevUiService
from plugins.services.install_service import PluginInstallService
from plugins.services.lifecycle_service import PluginLifecycleService
from plugins.services.presenter import PluginPresenter
from plugins.services.secret_slot_service import PluginSecretSlotService
from plugins.services.ui_service import PluginUiService


class PluginViewSet(
    OrgScopedViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Installed plugins of the active organization, and their lifecycle."""

    # JWT only: installing writes secrets, and a leaked API key must not mint them.
    permission_classes = [IsAuthenticated, DenyApiKeyAuth, HasOrgPermission]
    rbac_resource_type = ResourceType.PLUGINS
    rbac_action_map = {
        **DEFAULT_ACTION_MAP,
        "inspect": Permission.CREATE,
        "install": Permission.CREATE,
        "suspend": Permission.UPDATE,
        "resume": Permission.UPDATE,
        "retry": Permission.UPDATE,
        "secrets": Permission.UPDATE,
        "delete_preview": Permission.DELETE,
        "ui_session": Permission.USE,
        "nav": Permission.USE,
        "dev_ui": Permission.UPDATE,
    }
    queryset = Plugin.objects.order_by("name", "id")
    # An org has few plugins and the navigation needs all of them at once.
    pagination_class = None
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def list(self, request, *args, **kwargs):
        plugins = list(self.get_queryset())
        knowledge_service.refresh_states(plugins)
        return Response(PluginPresenter().present_many(plugins))

    def retrieve(self, request, *args, **kwargs):
        return self._detail(self.get_object())

    def destroy(self, request, *args, **kwargs):
        """Remove everything the plugin installed, then the plugin.

        Needs delete on every resource type that would be removed, not only `plugins:delete`.
        """
        PluginLifecycleService().delete(self.get_object(), user=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["get"], url_path="nav")
    def nav(self, request):
        """The navigation buttons: plugins whose page can open now, and nothing else about them.

        Needs only `plugins:use`, so it must not reveal what `plugins:read` guards.
        """
        candidates = list(self.get_queryset().filter(suspended=False).exclude(ui_entry=""))
        knowledge_service.refresh_states(candidates)
        return Response(
            [
                {
                    "id": plugin.pk,
                    "name": plugin.name,
                    "icon_data_url": plugin.icon_data_url or None,
                }
                for plugin in candidates
                if plugin.state == Plugin.State.READY
            ]
        )

    @action(detail=False, methods=["post"], url_path="inspect")
    def inspect(self, request):
        """Validate an uploaded plugin and return the install preview. Writes nothing."""
        serializer = PluginInspectRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        preview = PluginInstallService().inspect(
            serializer.validated_data["file"],
            user=request.user,
            org_id=self.get_active_org_id(),
        )
        return Response(preview, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="install")
    def install(self, request):
        """Install an uploaded plugin with its secret values; returns the plugin."""
        serializer = PluginInstallRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        plugin = PluginInstallService().install(
            serializer.validated_data["file"],
            secrets=serializer.validated_data["secrets"],
            user=request.user,
            org_id=self.get_active_org_id(),
        )
        return Response(PluginPresenter().present(plugin), status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="suspend")
    def suspend(self, request, pk=None):
        """Turn the plugin fully off and stop its live sessions."""
        return self._detail(PluginLifecycleService().suspend(self.get_object()))

    @action(detail=True, methods=["post"], url_path="resume")
    def resume(self, request, pk=None):
        return self._detail(PluginLifecycleService().resume(self.get_object()))

    @action(detail=True, methods=["post"], url_path="retry")
    def retry(self, request, pk=None):
        """Restart indexing of the knowledge that did not finish."""
        plugin = self.get_object()
        knowledge_service.retry(plugin)
        return self._detail(plugin)

    @action(detail=True, methods=["post"], url_path="secrets")
    def secrets(self, request, pk=None):
        """Re-enter secret slot values; optionally retry indexing afterwards."""
        plugin = self.get_object()
        # New values become new secrets, so this also needs the right to create secrets.
        assert_org_permission(
            request.user, self.get_active_org_id(), ResourceType.SECRETS, Permission.CREATE
        )
        serializer = PluginSecretsRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        PluginSecretSlotService().replace(
            plugin, serializer.validated_data["secrets"], user=request.user
        )
        if serializer.validated_data["retry_indexing"]:
            knowledge_service.refresh_states([plugin])
            if plugin.state == Plugin.State.NEEDS_ATTENTION and not plugin.suspended:
                knowledge_service.retry(plugin)
        return self._detail(plugin)

    @action(detail=True, methods=["get"], url_path="delete-preview")
    def delete_preview(self, request, pk=None):
        """What deleting the plugin would remove, and which permissions the caller lacks. Writes nothing."""
        return Response(
            PluginLifecycleService().delete_preview(self.get_object(), user=request.user)
        )

    @action(detail=True, methods=["post"], url_path="ui-session")
    def ui_session(self, request, pk=None):
        """The URL of the plugin's page for the sandboxed iframe, with an expiring token."""
        return Response(PluginUiService().open_session(self.get_object(), user=request.user))

    @action(detail=True, methods=["post", "delete"], url_path="dev-ui")
    def dev_ui(self, request, pk=None):
        """Load the plugin's page from the caller's localhost dev server (POST), or stop (DELETE).

        Only the caller gets the dev page, and only while the instance runs in plugin dev mode.
        """
        plugin = self.get_object()
        dev_ui = PluginDevUiService()
        if request.method == "DELETE":
            return self._detail(dev_ui.clear(plugin))
        # Before the body: with dev mode off the answer is 409 whatever was sent.
        dev_ui.require_enabled()
        serializer = PluginDevUiRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self._detail(
            dev_ui.set_url(plugin, serializer.validated_data["url"], user=request.user)
        )

    def _detail(self, plugin: Plugin) -> Response:
        knowledge_service.refresh_states([plugin])
        return Response(PluginPresenter().present(plugin))
