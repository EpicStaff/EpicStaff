from drf_spectacular.utils import extend_schema_serializer
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
