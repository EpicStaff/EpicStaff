"""Recycle-bin actions for every viewset whose items can be restored."""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rbac.access.gates import DenyApiKeyAuth, IsSuperadmin
from rbac.models.api_key import ApiKey
from rbac.models.enums import Permission
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from tables.serializers.recycle_bin_serializers import (
    RecycleBinBulkPurgeResponseSerializer,
    RecycleBinBulkRequestSerializer,
    RecycleBinBulkRestoreResponseSerializer,
    RecycleBinContentsSerializer,
    RecycleBinEntrySerializer,
    RecycleBinPageSerializer,
    RestoreResultSerializer,
)
from tables.services.recycle_bin.bin_contents_service import CONTENTS_FILTERS, BinContentsService
from tables.services.recycle_bin.bin_service import (
    DEFAULT_ENTRY_ORDERING,
    ENTRY_ORDERINGS,
    RecycleBinService,
)
from tables.services.recycle_bin.bulk_service import RecycleBinBulkService
from tables.services.recycle_bin.deleting import move_to_recycle_bin
from tables.services.recycle_bin.presentation import BinPresentation, bin_presentations
from tables.services.recycle_bin.purge_service import PurgeService
from tables.services.recycle_bin.registry import BinResource, bin_resources
from tables.services.recycle_bin.restore_service import RestoreService
from tables.services.recycle_bin.sources import RecycleBinSource
from tables.services.trigger_nodes import trigger_node_access

# Seeing the bin is a read and restoring brings an item back (a create). One bit
# per action, so the any-bit can() is exact. A restore that brings trigger nodes
# back also needs flows:USE, checked per item by TriggerNodeAccess. The purges are
# left out on purpose: they are superadmin-only (purge_permissions), and an
# unmapped action is denied, so a purge stays closed if a view ever loses that gate.
RECYCLE_BIN_ACTION_MAP = {
    "recycle_bin": Permission.READ,
    "recycle_bin_contents": Permission.READ,
    "restore": Permission.CREATE,
    "bulk_restore": Permission.CREATE,
}
# Purging is the one bin action that can't be undone, so only a superadmin may ask
# for it, and only from a user session. A file write over the storage quota is the
# one other way in: it purges the oldest storage entries for a session user with
# FILES:DELETE (StorageBinPurgeAccess), because the bin's bytes count toward the quota.
PURGE_ACTIONS = frozenset({"purge", "bulk_purge"})


class RecycleBinPagination(LimitOffsetPagination):
    """`?limit=`/`?offset=` paging of every bin list, storage's too.

    The limit is capped: every entry on a page costs its contents and details queries.
    """

    default_limit = 50
    max_limit = 100


class RecycleBinActionsMixin:
    """Add the bin actions to a viewset: `recycle-bin/` (list), `<pk>/recycle-bin-contents/`
    ("Show all"), `<pk>/restore/`, `<pk>/purge/`, and the bulk `recycle-bin/restore/` and
    `recycle-bin/purge/`.

    The viewset sets `recycle_bin_resource_key` (a key of `bin_resources()` and
    `bin_presentations()`), merges RECYCLE_BIN_ACTION_MAP into its `rbac_action_map`,
    and has `get_active_org_id()` (every OrgScoped* mixin provides it). Every action
    starts from RecycleBinService.binned(), so a row of another org, a live
    row, or a row the list hides is a 404.

    Both purges are superadmin-only and refuse API keys (403), as emptying the
    whole bin does: a purge can't be undone, so neither an org admin nor a leaked
    key may wipe the bin type by type. Listing and restoring follow the viewset's
    permission bits and stay open to API keys. A restore that brings trigger nodes
    back or live also needs flows:USE: a single restore is a 403, a bulk one
    reports the item as failed.

    `perform_destroy` bins the row and records the request user as who deleted it.
    A viewset that overrides it, or deletes outside it (a bulk delete), calls
    move_to_recycle_bin itself.
    """

    recycle_bin_resource_key: RecycleBinSource

    def get_permissions(self):
        permissions = super().get_permissions()
        if self.action in PURGE_ACTIONS:
            return purge_permissions(permissions)
        return permissions

    def perform_destroy(self, instance):
        move_to_recycle_bin(instance, self.request.user)

    def _bin_resource(self) -> BinResource:
        return bin_resources()[self.recycle_bin_resource_key]

    def _bin_presentation(self) -> BinPresentation:
        return bin_presentations()[self.recycle_bin_resource_key]

    def _get_binned_or_404(self, pk):
        # DRF's get_object_or_404 turns a non-numeric pk into a 404, not a 500.
        binned = RecycleBinService.binned(self._bin_resource(), self.get_active_org_id())
        return get_object_or_404(binned, pk=pk)

    @extend_schema(
        request=None,
        parameters=[
            OpenApiParameter("limit", int, description="Default 50, at most 100"),
            OpenApiParameter("offset", int),
            OpenApiParameter("search", str, description="Part of the item's name, in any case"),
            OpenApiParameter(
                "ordering", str, enum=list(ENTRY_ORDERINGS), description="Default: -deleted_at"
            ),
            OpenApiParameter(
                "contents",
                str,
                enum=list(CONTENTS_FILTERS),
                description="Only items whose restore brings back something (`some`) "
                "or nothing (`none`), as `contents_total` counts it",
            ),
        ],
        responses=RecycleBinPageSerializer,
    )
    @action(detail=False, methods=["get"], url_path="recycle-bin")
    def recycle_bin(self, request):
        # Filtered, sorted and counted in SQL; entries are built for the page only.
        resource = self._bin_resource()
        presentation = self._bin_presentation()
        org_id = self.get_active_org_id()
        paginator = RecycleBinPagination()
        rows = BinContentsService.entry_rows(
            resource,
            presentation,
            org_id,
            search=request.query_params.get("search", "").strip(),
            ordering=request.query_params.get("ordering", DEFAULT_ENTRY_ORDERING),
            contents=request.query_params.get("contents", ""),
        )
        page = paginator.paginate_queryset(rows, request, view=self)
        entries = BinContentsService.to_entries(
            resource, presentation, org_id, page, request=request
        )
        return paginator.get_paginated_response(RecycleBinEntrySerializer(entries, many=True).data)

    @extend_schema(request=None, responses=RecycleBinContentsSerializer)
    @action(detail=True, methods=["get"], url_path="recycle-bin-contents")
    def recycle_bin_contents(self, request, pk=None):
        """One binned item's contents, up to 5,000: "Show all" when the list's 100 aren't enough."""
        contents, total = BinContentsService.contents_of(
            self._bin_presentation(), self._get_binned_or_404(pk)
        )
        return Response(
            RecycleBinContentsSerializer({"contents": contents, "contents_total": total}).data
        )

    @extend_schema(request=None, responses=RestoreResultSerializer)
    @action(detail=True, methods=["post"], url_path="restore")
    def restore(self, request, pk=None):
        root = self._get_binned_or_404(pk)
        trigger_node_access.assert_user_may_restore(request.user, self.get_active_org_id(), root)
        result = RestoreService.restore(root)
        resource = self._bin_resource()
        restored = result.object
        return Response(
            RestoreResultSerializer(
                {
                    "id": restored.pk,
                    "name": getattr(restored, resource.name_field),
                    "renamed_from": result.renamed_from,
                    "links_restored": resource.keeps_references,
                }
            ).data
        )

    @extend_schema(request=None, responses={204: None})
    @action(detail=True, methods=["delete"], url_path="purge")
    def purge(self, request, pk=None):
        PurgeService.purge(self._get_binned_or_404(pk), actor=request_actor(request))
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        request=RecycleBinBulkRequestSerializer, responses=RecycleBinBulkRestoreResponseSerializer
    )
    @action(detail=False, methods=["post"], url_path="recycle-bin/restore")
    def bulk_restore(self, request):
        """Restore the selected items, or the whole bin with `all: true`. Failures are reported per item."""
        ids = self._bulk_ids(request)
        result = RecycleBinBulkService.restore_many(
            self._bin_resource(), self.get_active_org_id(), ids, request.user
        )
        resource = self._bin_resource()
        return Response(
            RecycleBinBulkRestoreResponseSerializer(
                {
                    "restored": [
                        {
                            "id": restored.object.pk,
                            "name": getattr(restored.object, resource.name_field),
                            "renamed_from": restored.renamed_from,
                            "links_restored": resource.keeps_references,
                        }
                        for restored in result.restored
                    ],
                    "failed": result.failed,
                }
            ).data
        )

    @extend_schema(
        request=RecycleBinBulkRequestSerializer, responses=RecycleBinBulkPurgeResponseSerializer
    )
    @action(detail=False, methods=["post"], url_path="recycle-bin/purge")
    def bulk_purge(self, request):
        """Delete the selected items for good, or empty the bin with `all: true`."""
        result = RecycleBinBulkService.purge_many(
            self._bin_resource(),
            self.get_active_org_id(),
            self._bulk_ids(request),
            actor=request_actor(request),
        )
        return Response(
            RecycleBinBulkPurgeResponseSerializer(
                {"purged": result.purged, "failed": result.failed}
            ).data
        )

    @staticmethod
    def _bulk_ids(request) -> list[int] | None:
        """The selected ids, or None for "every item in the bin"."""
        serializer = RecycleBinBulkRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return None if serializer.validated_data["all"] else serializer.validated_data["ids"]


def purge_permissions(view_permissions: list) -> list:
    """The gates of a purge: superadmin only, never an API key, then the view's own.

    Ahead of the view's gates, so a non-superadmin gets IsSuperadmin's 403 before any
    verb check or object lookup: the answer is the same for an id of another org.
    DenyApiKeyAuth goes first, so every API key, a superadmin's too, is told to use a session.
    """
    return [IsAuthenticated(), DenyApiKeyAuth(), IsSuperadmin(), *view_permissions]


def request_actor(request) -> str:
    """Who made the request, for the purge log: the user, and the API key if one was used."""
    # A system API key acts as SystemServicePrincipal, which has no pk.
    user_pk = getattr(request.user, "pk", None)
    who = f"user {user_pk}" if user_pk is not None else str(request.user)
    if isinstance(request.auth, ApiKey):
        return f"{who} via API key {request.auth.pk}"
    return who
