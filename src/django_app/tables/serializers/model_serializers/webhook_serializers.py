from tables.serializers.utils.secret_fields import SecretCharField
from loguru import logger
from rest_framework import serializers

from tables.models.webhook_models import (
    NgrokWebhookConfig,
    VoiceSettings,
    WebhookTrigger,
)


class NgrokWebhookConfigModelSerializer(serializers.ModelSerializer):
    auth_token = SecretCharField()
    webhook_full_url = serializers.SerializerMethodField()

    class Meta:
        model = NgrokWebhookConfig
        fields = [
            "id",
            "name",
            "auth_token",
            "domain",
            "region",
            "webhook_full_url",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance is None:
            self.fields["auth_token"].required = True
            self.fields["auth_token"].allow_null = False
            self.fields["auth_token"].allow_blank = False

    def get_webhook_full_url(self, instance: NgrokWebhookConfig):
        from tables.services.webhook_trigger_service import WebhookTriggerService

        try:
            return WebhookTriggerService().get_tunnel_url(ngrok_webhook_config=instance)
        except Exception as e:
            logger.error(f"Failed to read tunnel URL for '{instance.name}': {e}")
        return None


class WebhookTriggerSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookTrigger
        fields = "__all__"

    def validate(self, attrs):
        # ngrok_webhook_config is global platform infrastructure managed by
        # superadmins (the /api/ngrok-config/ endpoint is superadmin-only).
        # Non-superadmins may not assign it — drop it from their input so a
        # caller can't bind a webhook trigger to an arbitrary config by id (and
        # can't probe which config ids exist).
        #
        # TODO: TECH DEBT (per-org ngrok): NgrokWebhookConfig has no `org` column, so
        # this is a superadmin gate rather than org scoping. To make webhook
        # tunnels per-organization, add an `org` FK to NgrokWebhookConfig, scope
        # it, and replace this gate with OrgScopedPrimaryKeyRelatedField.
        request = self.context.get("request")
        is_superadmin = getattr(getattr(request, "user", None), "is_superadmin", False)
        if not is_superadmin:
            attrs.pop("ngrok_webhook_config", None)
        return attrs


class VoiceSettingsSerializer(serializers.ModelSerializer):
    twilio_auth_token = SecretCharField()
    voice_stream_url = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = VoiceSettings
        fields = [
            "twilio_account_sid",
            "twilio_auth_token",
            "voice_agent",
            "voice_agent_definition",
            "ngrok_config",
            "voice_stream_url",
        ]

    def validate(self, attrs):
        voice_agent = attrs.get(
            "voice_agent", self.instance.voice_agent if self.instance else None
        )
        voice_agent_definition = attrs.get(
            "voice_agent_definition",
            self.instance.voice_agent_definition if self.instance else None,
        )

        if voice_agent and voice_agent_definition:
            raise serializers.ValidationError(
                "Only one of 'voice_agent' or 'voice_agent_definition' may be set."
            )

        return attrs

    def get_voice_stream_url(self, obj):
        if not obj.ngrok_config:
            return None
        from tables.services.webhook_trigger_service import WebhookTriggerService

        try:
            base = WebhookTriggerService().get_tunnel_url(
                ngrok_webhook_config=obj.ngrok_config
            )
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
