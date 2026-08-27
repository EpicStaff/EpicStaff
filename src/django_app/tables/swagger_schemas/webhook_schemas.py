from drf_spectacular.utils import (
    OpenApiResponse,
    OpenApiExample,
    extend_schema_serializer,
)
from drf_spectacular.types import OpenApiTypes
from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE
from tables.serializers.model_serializers.node_serializers.trigger_serializers import (
    WebhookNodeAuthInputSerializer,
    WebhookTriggerNodeSerializer,
)


@extend_schema_serializer(component_name="WebhookTriggerNodeWrite")
class WebhookTriggerNodeWriteRequestSerializer(WebhookTriggerNodeSerializer):
    """drf-spectacular-only shape declaration for
    `WebhookTriggerNodeViewSet`'s create/update/partial_update request
    body. Never instantiated by the viewset for real request handling --
    wired via `request=` in `WEBHOOK_TRIGGER_NODE_CREATE`/`_UPDATE`/
    `_PARTIAL_UPDATE` below so the generated `WebhookTriggerNodeWriteRequest`
    / `PatchedWebhookTriggerNodeWriteRequest` OpenAPI components document
    the actual write shape (`{"enabled": bool}`) instead of omitting
    `webhook_node_auth` entirely.
    """

    webhook_node_auth = WebhookNodeAuthInputSerializer(required=False)


WEBHOOK_TRIGGER_NODE_CREATE = dict(
    request=WebhookTriggerNodeWriteRequestSerializer,
    description=(
        '`webhook_node_auth` accepts only `{"enabled": bool}` on write -- '
        "other sub-fields (scheme/header_name/signing_secret/etc.) are "
        "server-generated and any extra keys sent alongside `enabled` are "
        "silently ignored, not rejected. Omitting `webhook_node_auth` "
        "entirely leaves the default (auto-enabled) protection in place."
    ),
)

WEBHOOK_TRIGGER_NODE_UPDATE = dict(request=WebhookTriggerNodeWriteRequestSerializer)

WEBHOOK_TRIGGER_NODE_PARTIAL_UPDATE = dict(
    request=WebhookTriggerNodeWriteRequestSerializer
)

REGISTER_WEBHOOKS_POST = dict(
    summary="Register webhooks",
    description="Triggers registration of all webhooks via the webhook trigger service.",
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="OK",
            examples=[
                OpenApiExample(
                    "Webhooks registered",
                    value={},
                    response_only=True,
                ),
            ],
        ),
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Bad Request - Failed to register webhooks.",
            examples=[
                OpenApiExample(
                    "Registration error",
                    value={"error": "Failed to register webhooks."},
                    response_only=True,
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
    },
)
