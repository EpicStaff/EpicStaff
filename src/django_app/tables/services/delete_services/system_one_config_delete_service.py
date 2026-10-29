from tables.models import SystemOneConfig
from tables.services.delete_services.base_delete_service import BaseDeleteService
from tables.services.delete_services.usage import UsageReport, build_reports


class SystemOneConfigDeleteService(BaseDeleteService):
    """Delete service for SystemOneConfig entities.

    Nothing references a System One config yet, so there is no usage to report and
    nothing can block the delete. CDT prompt entries will reference it (a FLOWS
    bucket); that source goes here when they do.
    """

    model = SystemOneConfig

    def collect_usage(self, ids: list[int]) -> dict[int, UsageReport]:
        """One empty report per id -- see the class docstring."""
        return build_reports(ids, [])
