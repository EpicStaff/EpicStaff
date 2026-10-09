"""Recycle-bin actions for every viewset whose items can be restored."""

from drf_spectacular.utils import extend_schema
from rbac.models.api_key import ApiKey
from rbac.models.enums import Permission
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from tables.serializers.recycle_bin_serializers import (
    RecycleBinBulkPurgeResponseSerializer,
    RecycleBinBulkRequestSerializer,
    RecycleBinBulkRestoreResponseSerializer,
    RecycleBinContentsSerializer,
    RecycleBinEntrySerializer,
    RestoreResultSerializer,
)
from tables.services.recycle_bin.bin_contents_service import (
    BinContentsService,
    RecycleBinEntryWithContents,
)
from tables.services.recycle_bin.bin_service import RecycleBinService
from tables.services.recycle_bin.bulk_service import RecycleBinBulkService
from tables.services.recycle_bin.purge_service import PurgeService
from tables.services.recycle_bin.registry import BinResource, bin_resources
from tables.services.recycle_bin.restore_service import RestoreService

# Seeing the bin is a read, restoring brings an item back (a create), and
# purging finishes a delete. One bit per action, so the any-bit can() is exact.
RECYCLE_BIN_ACTION_MAP = {
    "recycle_bin": Permission.READ,
    "recycle_bin_contents": Permission.READ,
    "restore": Permission.CREATE,
    "purge": Permission.DELETE,
    "bulk_restore": Permission.CREATE,
    "bulk_purge": Permission.DELETE,
}


class RecycleBinActionsMixin:
    """Add the bin actions to a viewset: `recycle-bin/` (list), `<pk>/recycle-bin-contents/`
    ("Show all"), `<pk>/restore/`, `<pk>/purge/`, and the bulk `recycle-bin/restore/` and
    `recycle-bin/purge/`.

    The viewset sets `recycle_bin_resource_key` (a key of `bin_resources()`),
    merges RECYCLE_BIN_ACTION_MAP into its `rbac_action_map`, and has
    `get_active_org_id()` (every OrgScoped* mixin provides it). Every action
    starts from RecycleBinService.binned(), so a row of another org, a live
    row, or a row the list hides is a 404.
    """

    recycle_bin_resource_key: str
    recycle_bin_entry_serializer_class = RecycleBinEntrySerializer

    def _bin_resource(self) -> BinResource:
        return bin_resources()[self.recycle_bin_resource_key]

    def recycle_bin_entries(self, org_id: int) -> list[RecycleBinEntryWithContents]:
        """Entries the list action returns, each with what its restore brings back."""
        return BinContentsService.entries(
            self.recycle_bin_resource_key, self._bin_resource(), org_id
        )

    def _get_binned_or_404(self, pk):
        # DRF's get_object_or_404 turns a non-numeric pk into a 404, not a 500.
        binned = RecycleBinService.binned(self._bin_resource(), self.get_active_org_id())
        return get_object_or_404(binned, pk=pk)

    @extend_schema(request=None, responses=RecycleBinEntrySerializer(many=True))
    @action(detail=False, methods=["get"], url_path="recycle-bin")
    def recycle_bin(self, request):
        entries = self.recycle_bin_entries(self.get_active_org_id())
        return Response(self.recycle_bin_entry_serializer_class(entries, many=True).data)

    @extend_schema(request=None, responses=RecycleBinContentsSerializer)
    @action(detail=True, methods=["get"], url_path="recycle-bin-contents")
    def recycle_bin_contents(self, request, pk=None):
        """One binned item's contents, up to 5,000: "Show all" when the list's 100 aren't enough."""
        contents, total = BinContentsService.contents_of(
            self.recycle_bin_resource_key, self._get_binned_or_404(pk)
        )
        return Response(
            RecycleBinContentsSerializer({"contents": contents, "contents_total": total}).data
        )

    @extend_schema(request=None, responses=RestoreResultSerializer)
    @action(detail=True, methods=["post"], url_path="restore")
    def restore(self, request, pk=None):
        result = RestoreService.restore(self._get_binned_or_404(pk))
        restored = result.object
        return Response(
            RestoreResultSerializer(
                {
                    "id": restored.pk,
                    "name": getattr(restored, self._bin_resource().name_field),
                    "renamed_from": result.renamed_from,
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
            self._bin_resource(), self.get_active_org_id(), ids
        )
        name_field = self._bin_resource().name_field
        return Response(
            RecycleBinBulkRestoreResponseSerializer(
                {
                    "restored": [
                        {
                            "id": restored.object.pk,
                            "name": getattr(restored.object, name_field),
                            "renamed_from": restored.renamed_from,
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


def request_actor(request) -> str:
    """Who made the request, for the purge log: the user, and the API key if one was used."""
    # A system API key acts as SystemServicePrincipal, which has no pk.
    user_pk = getattr(request.user, "pk", None)
    who = f"user {user_pk}" if user_pk is not None else str(request.user)
    if isinstance(request.auth, ApiKey):
        return f"{who} via API key {request.auth.pk}"
    return who
