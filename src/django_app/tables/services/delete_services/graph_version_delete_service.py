from django.db import models

from tables.models import GraphVersion
from tables.services.delete_services.base_delete_service import BaseDeleteService
from tables.services.delete_services.usage import UsageReport, build_reports
from tables.services.rbac.effective_permissions import EffectivePermissions


class GraphVersionDeleteService(BaseDeleteService):
    """Delete service for GraphVersion entities.

    Nothing in the schema holds an FK to a GraphVersion: Graph has no
    current-version pointer, and restore / create-graph read a version's
    snapshot at call time without keeping a reference back to it. So there is
    no usage to report and nothing can block the delete.

    It still stays inside the family rather than opting out of it: it takes
    `effective` like every sibling and returns one empty report per id, so the
    response carries `skipped: []` and `usage: {...}` like everyone else's and a
    client needs no per-entity branch. The day something starts referencing a
    version, this is where its source goes.

    GraphVersion is a soft-delete root, so `BaseDeleteService._delete_rows`
    removes its rows one at a time.
    """

    model = GraphVersion

    def get_deletable_queryset(self, org_id: int) -> models.QuerySet:
        """Versions of this org's graphs. GraphVersion has no org column."""
        return self.model.objects.filter(graph__org_id=org_id)

    def collect_usage(
        self, ids: list[int], org_id: int, effective: EffectivePermissions
    ) -> dict[int, UsageReport]:
        """One empty report per id -- see the class docstring."""
        return build_reports(ids, [])
