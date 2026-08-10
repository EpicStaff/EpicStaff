from rest_framework import serializers

from tables.models.webhook_models import (
    LOCAL_ONLY_PROVIDERS,
    RealtimeChannel,
    TwilioChannel,
    WebhookTrigger,
)
from tables.serializers.base_serializers import WebhookTriggerNestedSerializer
from tables.models.llm_models import RealtimeConfig, RealtimeTranscriptionConfig
from tables.models.realtime_models import (
    ConversationRecording,
    ElevenLabsRealtimeConfig,
    GeminiRealtimeConfig,
    OpenAIRealtimeConfig,
    RealtimeAgent,
    RealtimeAgentChat,
    RealtimeSessionItem,
)
from tables.serializers.org_scoped_fields import OrgScopedPrimaryKeyRelatedField


class RealtimeAgentSerializer(serializers.ModelSerializer):
    # Org isolation: only configs from the caller's active org may be referenced.
    realtime_config = OrgScopedPrimaryKeyRelatedField(
        queryset=RealtimeConfig.objects.all(), required=False, allow_null=True
    )
    realtime_transcription_config = OrgScopedPrimaryKeyRelatedField(
        queryset=RealtimeTranscriptionConfig.objects.all(),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = RealtimeAgent
        exclude = ["agent"]


class RealtimeSessionItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = RealtimeSessionItem
        fields = "__all__"


class RealtimeAgentChatSerializer(serializers.ModelSerializer):
    class Meta:
        model = RealtimeAgentChat
        fields = "__all__"


class OpenAIRealtimeConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = OpenAIRealtimeConfig
        fields = "__all__"
        read_only_fields = ["org", "created_by"]


class ElevenLabsRealtimeConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = ElevenLabsRealtimeConfig
        fields = "__all__"
        read_only_fields = ["org", "created_by"]


class GeminiRealtimeConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeminiRealtimeConfig
        fields = "__all__"
        read_only_fields = ["org", "created_by"]


class TwilioChannelSerializer(serializers.ModelSerializer):
    webhook_trigger = OrgScopedPrimaryKeyRelatedField(
        queryset=WebhookTrigger.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = TwilioChannel
        fields = [
            "channel",
            "account_sid",
            "auth_token",
            "phone_number",
            "webhook_trigger",
        ]
        extra_kwargs = {"auth_token": {"write_only": True}}

    def validate(self, attrs):
        wt = attrs.get("webhook_trigger")
        provider_type = wt.provider_type if wt else None

        if provider_type and provider_type in LOCAL_ONLY_PROVIDERS:
            raise serializers.ValidationError(
                {
                    "webhook_trigger": (
                        "Localhost webhook provider is not reachable by Twilio. "
                        "Use ngrok or a publicly accessible provider."
                    )
                }
            )
        return attrs


class _TwilioChannelReadSerializer(serializers.ModelSerializer):
    """Read-only variant that expands webhook_trigger so downstream consumers get live_url."""

    webhook_trigger = WebhookTriggerNestedSerializer(read_only=True)

    class Meta:
        model = TwilioChannel
        fields = ["channel", "account_sid", "phone_number", "webhook_trigger"]


class RealtimeChannelSerializer(serializers.ModelSerializer):
    twilio = _TwilioChannelReadSerializer(read_only=True)
    realtime_agent = OrgScopedPrimaryKeyRelatedField(
        queryset=RealtimeAgent.objects.all(),
        org_lookup="agent__org_id",
        required=False,
        allow_null=True,
    )

    class Meta:
        model = RealtimeChannel
        fields = "__all__"
        read_only_fields = ["org", "created_by"]


class _TwilioChannelInternalSerializer(_TwilioChannelReadSerializer):
    """Internal-only variant of `_TwilioChannelReadSerializer` that includes `auth_token`.

    Used exclusively by `RealtimeChannelViewSet.lookup_by_token`, which is gated by
    `IsApiKeyAuthenticated` (the trusted `realtime`/`voice_app` services only, never a
    logged-in user). That caller needs `auth_token` to validate the `X-Twilio-Signature`
    header on inbound Twilio webhook requests. Do NOT reuse this serializer for any
    user-facing endpoint — that would reopen the EST-3633 leak.
    """

    class Meta(_TwilioChannelReadSerializer.Meta):
        fields = _TwilioChannelReadSerializer.Meta.fields + ["auth_token"]


class RealtimeChannelInternalSerializer(RealtimeChannelSerializer):
    """Internal-only variant of `RealtimeChannelSerializer` used by `lookup_by_token`.

    Nests `_TwilioChannelInternalSerializer` so the response includes `twilio.auth_token`.
    Only ever instantiated behind `IsApiKeyAuthenticated` — see
    `RealtimeChannelViewSet.lookup_by_token`.
    """

    twilio = _TwilioChannelInternalSerializer(read_only=True)


class ConversationRecordingSerializer(serializers.ModelSerializer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from tables.models.realtime_models import (
            RealtimeAgentChat as _RealtimeAgentChat,
        )

        self.fields["rt_agent_chat"] = serializers.PrimaryKeyRelatedField(
            queryset=_RealtimeAgentChat.objects.all(),
            required=False,
            allow_null=True,
        )

    class Meta:
        model = ConversationRecording
        fields = "__all__"
        read_only_fields = ["file_size", "audio_format", "created_at"]


class RealtimeAgentReadSerializer(serializers.ModelSerializer):
    openai_config = OpenAIRealtimeConfigSerializer(read_only=True)
    elevenlabs_config = ElevenLabsRealtimeConfigSerializer(read_only=True)
    gemini_config = GeminiRealtimeConfigSerializer(read_only=True)

    class Meta:
        model = RealtimeAgent
        exclude = ["agent"]


class RealtimeAgentWriteSerializer(serializers.ModelSerializer):
    voice = serializers.CharField(allow_blank=True, default="alloy")
    openai_config = OrgScopedPrimaryKeyRelatedField(
        queryset=OpenAIRealtimeConfig.objects.all(), required=False, allow_null=True
    )
    elevenlabs_config = OrgScopedPrimaryKeyRelatedField(
        queryset=ElevenLabsRealtimeConfig.objects.all(),
        required=False,
        allow_null=True,
    )
    gemini_config = OrgScopedPrimaryKeyRelatedField(
        queryset=GeminiRealtimeConfig.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = RealtimeAgent
        exclude = ["agent"]

    def validate(self, attrs):
        openai_config = attrs.get(
            "openai_config", getattr(self.instance, "openai_config", None)
        )
        elevenlabs_config = attrs.get(
            "elevenlabs_config", getattr(self.instance, "elevenlabs_config", None)
        )
        gemini_config = attrs.get(
            "gemini_config", getattr(self.instance, "gemini_config", None)
        )

        set_count = sum(
            [
                openai_config is not None,
                elevenlabs_config is not None,
                gemini_config is not None,
            ]
        )

        if set_count > 1:
            raise serializers.ValidationError(
                "A RealtimeAgent may have at most one provider config set "
                "(openai_config, elevenlabs_config, or gemini_config)."
            )

        return attrs
