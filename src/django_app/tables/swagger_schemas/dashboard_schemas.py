from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiResponse

from tables.serializers.dashboard_serializers import DashboardReportSerializer
from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE

DASHBOARD_REPORT_GET = {
    "summary": "Get the dashboard summary",
    "description": (
        "Returns the prepared dashboard summary of the active organization: resource "
        "totals, active triggers, live sessions and knowledge indexing usage."
    ),
    "responses": {
        200: DashboardReportSerializer,
        401: UNAUTHORIZED_401_RESPONSE,
        403: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="The caller has no View Dashboard permission in the active organization.",
        ),
        404: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="The first summary of this organization is not built yet.",
            examples=[
                OpenApiExample(
                    "Report not ready",
                    value={"code": "report_not_ready"},
                    response_only=True,
                ),
            ],
        ),
    },
}
