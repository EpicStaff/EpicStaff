from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.settings import api_settings
from tables.serializers.serializers import (
    InspectImportRequestSerializer,
    ToolUsageDetailSerializer,
    ToolUsageSerializer,
)
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


class TriggerNodeRunPermissionMixin:
    """Require FLOWS.RUN, besides the action's own bit, to create or edit a trigger node.

    For the webhook, Telegram and schedule trigger node viewsets: a trigger node
    starts flow runs by itself. Place it after the org-scoping mixin. Reads and
    deletes keep their usual gate.

    `create` is checked with the other permission checks, as there is no node to
    look up. The detail actions are checked right after the org-scoped lookup, so
    another org's node or a missing id is a 404 before any RUN 403, and the 403
    still comes before the body is validated or anything is written or sent.
    """

    run_gated_detail_actions = frozenset({"update", "partial_update", "register_webhook"})

    def check_permissions(self, request):
        super().check_permissions(request)
        if self.action == "create":
            trigger_node_access.assert_may_write(request.user, self.get_active_org_id())

    def get_object(self):
        instance = super().get_object()
        if self.action in self.run_gated_detail_actions:
            trigger_node_access.assert_may_write(self.request.user, self.get_active_org_id())
        return instance


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
