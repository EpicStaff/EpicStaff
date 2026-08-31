from rest_framework import serializers

from tables.models.secret_models import Secret
from tables.models.webhook_models import (
    VoiceSettings,
    WebhookTrigger,
)
from tables.services.secrets import secret_resolver


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
    """Superadmin-facing (JWT session) serializer for the `VoiceSettings`
    global singleton.

    Twilio credentials are managed via `*_secret_id` FK fields — the same
    shape as `TwilioChannelSerializer.auth_token_secret_id` — never as raw
    plaintext. `VoiceSettings` has no owning organization (it is the one
    truly global, non-org-scoped resource that references `Secret`), so the
    queryset here is intentionally unscoped by org; this is safe only because
    the view restricts access to `IsSuperadmin`, who already bypasses
    per-org RBAC everywhere else (see `HasOrgPermission`).
    """

    twilio_account_sid_secret_id = serializers.PrimaryKeyRelatedField(
        queryset=Secret.objects.all(),
        source="twilio_account_sid_secret",
        required=False,
        allow_null=True,
    )
    twilio_auth_token_secret_id = serializers.PrimaryKeyRelatedField(
        queryset=Secret.objects.all(),
        source="twilio_auth_token_secret",
        required=False,
        allow_null=True,
    )
    voice_stream_url = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = VoiceSettings
        fields = [
            "twilio_account_sid_secret_id",
            "twilio_auth_token_secret_id",
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


class VoiceSettingsInternalSerializer(VoiceSettingsSerializer):
    """Internal-only variant that returns the *resolved* plaintext Twilio
    credentials, in addition to the `*_secret_id` fields.

    Used exclusively when `VoiceSettingsView` is called by a `key_type=SYSTEM`
    API key — the `realtime` service's legacy `POST /voice` webhook fetches
    this endpoint to validate the inbound `X-Twilio-Signature` header against
    the real `twilio_auth_token`, and needs the plaintext value to do so. Never
    served to a JWT-authenticated (super)admin session — same trust boundary
    as `_TwilioChannelInternalSerializer`.

    `VoiceSettings` itself has no owning organization (it is the one
    genuinely global, non-org-scoped singleton that references `Secret`),
    but every `Secret` row still has a real owning org (`Secret.org_id` is
    DB-level `NOT NULL` — see 0221_voice_settings_twilio_secret.py). A
    superadmin may point `*_secret_id` at a `Secret` from any org (no
    per-org scoping is possible for a resource with no org of its own), so
    resolution here reads the org directly off each referenced `Secret` row
    and resolves through the standard `secret_resolver.resolve()`.
    """

    twilio_account_sid = serializers.SerializerMethodField()
    twilio_auth_token = serializers.SerializerMethodField()

    class Meta(VoiceSettingsSerializer.Meta):
        fields = VoiceSettingsSerializer.Meta.fields + [
            "twilio_account_sid",
            "twilio_auth_token",
        ]

    @staticmethod
    def _resolve(secret: Secret | None) -> str | None:
        if secret is None:
            return None
        return secret_resolver.resolve(
            secret_id=secret.pk,
            org_id=secret.org_id,
            context="VoiceSettings",
        )

    def get_twilio_account_sid(self, obj: VoiceSettings) -> str | None:
        return self._resolve(obj.twilio_account_sid_secret)

    def get_twilio_auth_token(self, obj: VoiceSettings) -> str | None:
        return self._resolve(obj.twilio_auth_token_secret)
