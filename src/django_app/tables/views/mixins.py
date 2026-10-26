from django.db import IntegrityError, transaction
from rbac.access.effective import EffectivePermissions
from rbac.access.resolver import PermissionResolver
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.settings import api_settings
from tables.serializers.serializers import (
    BulkDeleteQuerySerializer,
    BulkDeleteRequestSerializer,
    BulkDeleteResultSerializer,
    InspectImportRequestSerializer,
    ToolUsageDetailSerializer,
    ToolUsageSerializer,
)
from tables.services.delete_services import BaseDeleteService
from tables.services.tools_usage_service import ToolNotFoundError, get_tools_usage
from tables.services.trigger_nodes import trigger_node_access
from utils.logger import logger


class CopyActionMixin:
    """Mixin that adds a ``copy`` action to a ViewSet.

    Requires two class attributes:
        copy_service_class: Copy service to instantiate.
        copy_serializer_class: Serializer for the response.
    """

    copy_service_class = None
    copy_serializer_class = None

    @action(detail=True, methods=["post"], url_path="copy")
    def copy(self, request, pk: int):
        instance = self.get_object()
        self.check_copy_allowed(request, instance)
        name = request.data.get("name") if isinstance(request.data, dict) else None
        # Org-scoped viewsets stamp the copy with the active org so the new row
        # satisfies the NOT NULL org constraint. This covers tool copies too:
        # PythonCodeToolViewSet (OrgScopedHybridViewSetMixin) and McpToolViewSet
        # (OrgScopedViewSetMixin) both expose get_active_org_id, so their copies
        # also receive an org id.
        extra = {}
        if hasattr(self, "get_active_org_id"):
            extra["org_id"] = self.get_active_org_id()
        try:
            with transaction.atomic():
                new_instance = self.copy_service_class().copy(
                    instance, name=name, user=request.user, **extra
                )
        except IntegrityError:
            logger.warning(
                "Copy of %s#%s raced on a unique constraint; client should retry.",
                self.copy_service_class.__name__,
                pk,
            )
            return Response(
                {"message": "A copy with that name was just created; please retry."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            self.copy_serializer_class(new_instance, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    def check_copy_allowed(self, request, instance) -> None:
        """Raise to refuse copying `instance`; runs after the org-scoped fetch, before writing.

        Allows by default. A viewset whose copies need more than the action's own
        permission overrides it.
        """


class TriggerNodeUsePermissionMixin:
    """Require FLOWS.USE, besides the action's own bit, to create or edit a trigger node.

    For the webhook, Telegram and schedule trigger node viewsets: a trigger node
    starts flow runs by itself. Place it after the org-scoping mixin. Reads and
    deletes keep their usual gate.

    `create` is checked with the other permission checks, as there is no node to
    look up. The detail actions are checked right after the org-scoped lookup, so
    another org's node or a missing id is a 404 before any USE 403, and the 403
    still comes before the body is validated or anything is written or sent.
    """

    use_gated_detail_actions = frozenset({"update", "partial_update", "register_webhook"})

    def check_permissions(self, request):
        super().check_permissions(request)
        if self.action == "create":
            trigger_node_access.assert_may_write(request.user, self.get_active_org_id())

    def get_object(self):
        instance = super().get_object()
        if self.action in self.use_gated_detail_actions:
            trigger_node_access.assert_may_write(self.request.user, self.get_active_org_id())
        return instance


class BulkDeleteActionMixin:
    """Adds a ``bulk-delete`` action and a usage-guarded ``perform_destroy``.

    Requires `delete_service_class` and `"bulk_delete": Permission.DELETE` in
    `rbac_action_map`; place it after the org-scoping mixin. Must precede
    `RecycleBinActionsMixin`, whose `perform_destroy` does not call `super()`.
    """

    delete_service_class = None

    def get_delete_service(self) -> BaseDeleteService:
        if not self.delete_service_class:
            raise NotImplementedError(f"{self.__class__.__name__} must set delete_service_class.")
        return self.delete_service_class(
            org_id=self.get_active_org_id(),
            permissions=self.get_effective_permissions(),
            user=self.request.user,
        )

    def get_effective_permissions(self) -> EffectivePermissions:
        """The caller's permissions in the active org, resolved fresh per call."""
        return PermissionResolver().resolve(user=self.request.user, org_id=self.get_active_org_id())

    def perform_destroy(self, instance) -> None:
        service = self.get_delete_service()
        # assert_deletable locks the row, so check and delete share one transaction.
        with transaction.atomic():
            service.assert_deletable(instance)
            super().perform_destroy(instance)

    @action(detail=False, methods=["post"], url_path="bulk-delete")
    def bulk_delete(self, request):
        query = BulkDeleteQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        body = BulkDeleteRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        service = self.get_delete_service()
        dry_run = query.validated_data["dry_run"]
        ids = body.validated_data["ids"]
        result = service.preview(ids) if dry_run else service.delete(ids)

        logger.info(
            "Bulk delete {}: org={} user={} dry_run={} deleted={} skipped={} not_found={}",
            service.model.__name__,
            service.org_id,
            # A system API key's principal has no pk; its str() names it.
            getattr(request.user, "pk", request.user),
            dry_run,
            result.deleted_count,
            len(result.skipped),
            len(result.not_found_ids),
        )
        is_multi_status = not dry_run and result.is_partial
        return Response(
            BulkDeleteResultSerializer(result).data,
            status=status.HTTP_207_MULTI_STATUS if is_multi_status else status.HTTP_200_OK,
        )


class ToolUsageActionsMixin:
    MAX_USAGE_IDS = api_settings.PAGE_SIZE

    def _usage_response(self, request, tool_model):
        ids = request.data.get("ids")
        if ids is not None:
            # bool is an int subclass in Python, so isinstance(True, int) is
            # True — without excluding bool explicitly, {"ids": [true]} would
            # silently pass validation and get treated as tool id 1.
            if not isinstance(ids, list) or not all(
                isinstance(i, int) and not isinstance(i, bool) for i in ids
            ):
                return Response(
                    {"detail": "ids must be a list of integers."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if len(ids) > self.MAX_USAGE_IDS:
                return Response(
                    {"detail": (f"maximum {self.MAX_USAGE_IDS} allowed, got {len(ids)}")},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            ids = set(ids)

        rows = get_tools_usage(self.get_active_org_id(), tool_model, ids=ids)

        if not ids and len(rows) > self.MAX_USAGE_IDS:
            return Response(
                {
                    "detail": (
                        f"more than {self.MAX_USAGE_IDS} tools visible to this "
                        "org; pass explicit `ids` (<= the max) to scope the "
                        "request instead of omitting it."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = ToolUsageSerializer(rows, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def _usage_detail_response(self, pk, service_fn, not_found_name):
        org_id = self.get_active_org_id()
        try:
            tool_id = int(pk)
        except (TypeError, ValueError) as e:
            raise NotFound(f"{not_found_name} {pk} not found.") from e
        try:
            detail = service_fn(tool_id, org_id)
        except ToolNotFoundError as e:
            raise NotFound(f"{not_found_name} {pk} not found.") from e
        serializer = ToolUsageDetailSerializer(detail)
        return Response(serializer.data, status=status.HTTP_200_OK)


class InspectActionMixin:
    """Adds a ``inspect_import`` action to an import-capable ViewSet."""

    @action(detail=False, methods=["post"], url_path="import/inspect")
    def inspect_import(self, request):
        serializer = InspectImportRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = self.import_export_service.inspect_entity(
            serializer.validated_data["file"], org_id=self.get_active_org_id()
        )
        return Response(result, status=status.HTTP_200_OK)
