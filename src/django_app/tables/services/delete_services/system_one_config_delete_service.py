from rbac.models.enums import ResourceType
from tables.models import ClassificationDecisionTablePrompt, SystemOneConfig
from tables.services.delete_services.base_delete_service import BaseDeleteService
from tables.services.delete_services.usage import (
    BucketCollector,
    UsageReport,
    build_reports,
)


class SystemOneConfigDeleteService(BaseDeleteService):
    """Delete service for SystemOneConfig entities.

    One FLOWS bucket: the Flows whose decision-table prompt entries use the config.
    The sample names the Flow, not the prompt row, as it does for LLM configs.
    Deleting a used config clears the entry's link and never blocks on it.
    """

    model = SystemOneConfig

    def collect_usage(self, ids: list[int]) -> dict[int, UsageReport]:
        """Flows referencing each config."""
        flows = BucketCollector.for_resource(ResourceType.FLOWS, self.effective)
        if ids:
            flows.add_rows(
                ClassificationDecisionTablePrompt.objects.filter(
                    cdt_node__graph__org_id=self.org_id, system_one_config_id__in=ids
                )
                .values_list("system_one_config_id", "cdt_node__graph_id", "cdt_node__graph__name")
                .distinct(),
            )
        return build_reports(ids, [flows])
