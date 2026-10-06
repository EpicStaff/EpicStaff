"""Recycle-bin actions for every viewset whose items can be restored."""

from drf_spectacular.utils import extend_schema
from rbac.models.api_key import ApiKey
from rbac.models.enums import Permission
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from tables.serializers.recycle_bin_serializers import (
    RecycleBinEntrySerializer,
    RestoreResultSerializer,
)
from tables.services.recycle_bin.bin_service import RecycleBinEntry, RecycleBinService
from tables.services.recycle_bin.purge_service import PurgeService
from tables.services.recycle_bin.registry import BinResource, bin_resources
from tables.services.recycle_bin.restore_service import RestoreService

# Seeing the bin is a read, restoring brings an item back (a create), and
# purging finishes a delete. One bit per action, so the any-bit can() is exact.
RECYCLE_BIN_ACTION_MAP = {
    "recycle_bin": Permission.READ,
    "restore": Permission.CREATE,
    "purge": Permission.DELETE,
}


class RecycleBinActionsMixin:
    """Add `recycle-bin/` (list), `<pk>/restore/` and `<pk>/purge/` to a viewset.

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

    def recycle_bin_entries(self, org_id: int) -> list[RecycleBinEntry]:
        """Entries the list action returns. A viewset can add fields to them."""
        return RecycleBinService.entries(self._bin_resource(), org_id)

    def _get_binned_or_404(self, pk):
        # DRF's get_object_or_404 turns a non-numeric pk into a 404, not a 500.
        binned = RecycleBinService.binned(self._bin_resource(), self.get_active_org_id())
        return get_object_or_404(binned, pk=pk)

    @extend_schema(request=None, responses=RecycleBinEntrySerializer(many=True))
    @action(detail=False, methods=["get"], url_path="recycle-bin")
    def recycle_bin(self, request):
        entries = self.recycle_bin_entries(self.get_active_org_id())
        return Response(self.recycle_bin_entry_serializer_class(entries, many=True).data)

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


def request_actor(request) -> str:
    """Who made the request, for the purge log: the user, and the API key if one was used."""
    # A system API key acts as SystemServicePrincipal, which has no pk.
    user_pk = getattr(request.user, "pk", None)
    who = f"user {user_pk}" if user_pk is not None else str(request.user)
    if isinstance(request.auth, ApiKey):
        return f"{who} via API key {request.auth.pk}"
    return who
