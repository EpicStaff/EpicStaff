from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiResponse

from tables.serializers.dashboard_serializers import (
    DashboardReportSerializer,
    DashboardStatsQuerySerializer,
)
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

DASHBOARD_STATS_GET = {
    "summary": "Get dashboard statistics for a period",
    "description": (
        "Returns finished sessions by status and token totals of the active organization "
        "for each day, month or year from 'from' to 'to' (UTC). Periods without sessions "
        "have zeros."
    ),
    "parameters": [DashboardStatsQuerySerializer],
    "responses": {
        200: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            examples=[
                OpenApiExample(
                    "One day",
                    value={
                        "periods": [
                            {
                                "period": "2026-11-23",
                                "by_status": {"end": 12, "error": 2, "stop": 0, "expired": 1},
                                "tokens": {
                                    "prompt": 5300,
                                    "completion": 1200,
                                    "cached": 800,
                                    "total": 6500,
                                    "cost_usd": "0.012300",
                                },
                            }
                        ]
                    },
                    response_only=True,
                ),
            ],
        ),
        400: OpenApiResponse(
            response=OpenApiTypes.OBJECT, description="'from', 'to' or 'group' is invalid."
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        403: DASHBOARD_REPORT_GET["responses"][403],
    },
}
