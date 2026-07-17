from rest_framework import serializers

from tables.models.webhook_models import (
    NgrokWebhookConfig,
    VoiceSettings,
    WebhookTrigger,
)
from utils.logger import logger


class NgrokWebhookConfigModelSerializer(serializers.ModelSerializer):
    """Direct CRUD shape for NgrokWebhookConfigViewSet (superadmin-only).

    NgrokWebhookConfig is now a OneToOne child of WebhookTrigger (see
    tables/models/webhook_models.py) rather than a standalone globally
    FK-referenced row, so `trigger` is exposed as a required field here.
    """

    webhook_full_url = serializers.SerializerMethodField()

    class Meta:
        model = NgrokWebhookConfig
        fields = [
            "id",
            "name",
            "auth_token",
            "domain",
            "region",
            "trigger",
            "webhook_full_url",
        ]

    def get_webhook_full_url(self, instance: NgrokWebhookConfig):
        from tables.services.webhook_trigger_service import WebhookTriggerService

        try:
            return WebhookTriggerService().get_tunnel_url(instance.trigger)
        except Exception as e:
            logger.error(f"Failed to read tunnel URL for '{instance.name}': {e}")
        return None


class WebhookTriggerSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookTrigger
        fields = "__all__"

    def validate(self, attrs):
        # NOTE: main's superadmin gate (dropping `ngrok_webhook_config` from
        # attrs for non-superadmins) no longer applies here. In the current
        # schema, WebhookTrigger only has `path` / `provider_type` — the
        # ngrok/localhost config moved to the related NgrokWebhookConfig /
        # LocalhostWebhookConfig models (see tables/models/webhook_models.py),
        # which are not part of this serializer's fields ("__all__" on
        # WebhookTrigger resolves to id/path/provider_type only). The
        # equivalent gate for the actual nested ngrok payload lives where that
        # payload is written: WebhookCreationMixin._get_or_create_webhook_trigger
        # (tables/serializers/utils/mixins.py), which now drops `ngrok_config`
        # for non-superadmins before calling NgrokWebhookConfig.update_or_create.
        instance = self.instance or WebhookTrigger()
        for k, v in attrs.items():
            setattr(instance, k, v)
        try:
            instance.validate_unique()
        except serializers.ValidationError as e:
            raise serializers.ValidationError(
                e.message_dict if hasattr(e, "message_dict") else e.messages
            )
        return attrs


class VoiceSettingsSerializer(serializers.ModelSerializer):
    voice_stream_url = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = VoiceSettings
        fields = [
            "twilio_account_sid",
            "twilio_auth_token",
            "voice_agent",
            "ngrok_config",
            "voice_stream_url",
        ]

    def get_voice_stream_url(self, obj):
        if not obj.ngrok_config:
            return None
        from tables.services.webhook_trigger_service import WebhookTriggerService

        try:
            base = WebhookTriggerService()._get_tunnel_url(obj.ngrok_config)
        except Exception:
            base = None
        if not base and obj.ngrok_config.domain:
            base = f"https://{obj.ngrok_config.domain}"
        if base:
            return (
                base.rstrip("/")
                .replace("https://", "wss://")
                .replace("http://", "wss://")
                + "/voice/stream"
            )
        return None
