from django.db import models
from tables.models import GraphVersion
from tables.services.delete_services.base_delete_service import BaseDeleteService
from tables.services.delete_services.usage import UsageReport, build_reports


class GraphVersionDeleteService(BaseDeleteService):
    """Delete service for GraphVersion: nothing holds an FK to a version, so nothing blocks."""

    model = GraphVersion

    def get_deletable_queryset(self) -> models.QuerySet:
        """Versions of this org's graphs; GraphVersion has no org column."""
        return self.model.objects.filter(graph__org_id=self.org_id)

    def collect_usage(self, ids: list[int]) -> dict[int, UsageReport]:
        """One empty report per id."""
        return build_reports(ids, [])
