from tables.models.webhook_models import NgrokWebhookConfig, WebhookTrigger
from rest_framework import serializers


class WebhookTriggerNestedSerializer(serializers.ModelSerializer):
    ngrok_webhook_config = serializers.PrimaryKeyRelatedField(
        queryset=NgrokWebhookConfig.objects.all(),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = WebhookTrigger
        fields = ["path", "ngrok_webhook_config"]
        extra_kwargs = {"path": {"validators": []}}
        validators = []
