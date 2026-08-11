from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiResponse

SECRET_USAGE_GET = dict(
    summary="Secret usage",
    description=(
        "Every resource in the active organization that references this secret. "
        "A category is present only when it has items, so an unused secret returns "
        "an empty list. Flow entries group their secret-using nodes; `node_type` "
        "values are the frontend node-type identifiers."
    ),
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="Usage grouped by category",
            examples=[
                OpenApiExample(
                    "In use across three categories",
                    value={
                        "total": 4,
                        "categories": [
                            {
                                "key": "flows",
                                "items": [
                                    {
                                        "id": 12,
                                        "name": "Payments flow",
                                        "nodes": [
                                            {
                                                "name": "charge_card",
                                                "node_type": "python",
                                                "code_field": "python_code",
                                            },
                                            {
                                                "name": "classify_tier",
                                                "node_type": (
                                                    "classification-decision-table"
                                                ),
                                                "code_field": "post_python_code",
                                            },
                                            {
                                                "name": "classify_tier",
                                                "node_type": (
                                                    "classification-decision-table"
                                                ),
                                                "code_field": "pre_python_code",
                                            },
                                            {
                                                "name": "route_by_tier",
                                                "node_type": "edge",
                                                "code_field": "python_code",
                                            },
                                        ],
                                    },
                                    {
                                        "id": 31,
                                        "name": "Refunds",
                                        "nodes": [
                                            {
                                                "name": "notify",
                                                "node_type": "telegram-trigger",
                                                "code_field": None,
                                            }
                                        ],
                                    },
                                ],
                            },
                            {"key": "tools", "items": [{"name": "Stripe refund"}]},
                            {
                                "key": "llm_configs",
                                "items": [{"name": "gpt-4o prod"}],
                            },
                        ],
                    },
                    response_only=True,
                ),
                OpenApiExample(
                    "Unused",
                    value={"total": 0, "categories": []},
                    response_only=True,
                ),
            ],
        ),
        404: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description=(
                "No such secret in the active organization. Another "
                "organization's secret is indistinguishable from a missing one."
            ),
        ),
    },
)
