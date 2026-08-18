from tables.serializers.utils.secret_fields import SecretCharField
from rest_framework import serializers

from tables.models.webhook_models import (
    VoiceSettings,
    WebhookTrigger,
)


class WebhookTriggerSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookTrigger
        fields = ["id", "path", "provider_type"]

    def validate(self, attrs):
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
