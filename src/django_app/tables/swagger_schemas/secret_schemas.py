from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiResponse

SECRET_USAGE_GET = {
    "summary": "Secret usage",
    "description": (
        "Every resource in the active organization that references this secret. "
        "A category is present only when it has items, so an unused secret returns "
        "an empty list. Flow entries group their secret-using nodes, one entry per "
        "code block that uses the secret (`code_field`, null for a node that "
        "references the secret by field rather than in code), so a decision table "
        "using it in both blocks appears twice with the same node `id`. A node's `id` is "
        "its identity — names repeat within a flow — and `node_number` is its "
        "display-only badge number, which may be null. `node_type` "
        "values are the frontend node-type identifiers. Items in the other "
        "categories carry a `type` naming which model they are, because a category "
        "can hold several — `llm_configs` folds four and `tools` folds two, and two "
        "of them may share a name. "
        "Only resources the requesting user has READ permission on are listed; "
        "`readable_total` counts those, and `hidden_total` counts the referencing "
        "resources withheld, so a secret that is referenced only by resources the "
        "caller cannot see reports `readable_total: 0` with a non-zero "
        "`hidden_total`."
    ),
    "responses": {
        200: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="Usage grouped by category",
            examples=[
                OpenApiExample(
                    "In use across three categories",
                    value={
                        "readable_total": 4,
                        "hidden_total": 0,
                        "categories": [
                            {
                                "key": "flows",
                                "items": [
                                    {
                                        "id": 12,
                                        "name": "Payments flow",
                                        "nodes": [
                                            {
                                                "id": 101,
                                                "node_number": 1,
                                                "name": "charge_card",
                                                "node_type": "python",
                                                "code_field": "python_code",
                                            },
                                            {
                                                "id": 102,
                                                "node_number": 2,
                                                "name": "classify_tier",
                                                "node_type": ("classification-decision-table"),
                                                "code_field": "post_python_code",
                                            },
                                            {
                                                "id": 102,
                                                "node_number": 2,
                                                "name": "classify_tier",
                                                "node_type": ("classification-decision-table"),
                                                "code_field": "pre_python_code",
                                            },
                                            {
                                                "id": 107,
                                                "node_number": 5,
                                                "name": "stripe_webhook",
                                                "node_type": "webhook-trigger",
                                                "code_field": "python_code",
                                            },
                                        ],
                                    },
                                    {
                                        "id": 31,
                                        "name": "Refunds",
                                        "nodes": [
                                            {
                                                "id": 240,
                                                "node_number": 3,
                                                "name": "notify",
                                                "node_type": "telegram-trigger",
                                                "code_field": None,
                                            }
                                        ],
                                    },
                                ],
                            },
                            {
                                "key": "tools",
                                "items": [{"name": "Stripe refund", "type": "mcp_tool"}],
                            },
                            {
                                "key": "llm_configs",
                                "items": [{"name": "gpt-4o prod", "type": "llm_config"}],
                            },
                        ],
                    },
                    response_only=True,
                ),
                OpenApiExample(
                    "Unused",
                    value={
                        "readable_total": 0,
                        "hidden_total": 0,
                        "categories": [],
                    },
                    response_only=True,
                ),
                OpenApiExample(
                    "Referenced only by resources the caller cannot read",
                    value={
                        "readable_total": 0,
                        "hidden_total": 2,
                        "categories": [],
                    },
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
}
