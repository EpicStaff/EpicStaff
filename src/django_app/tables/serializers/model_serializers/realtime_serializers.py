from rest_framework import serializers

from tables.models.secret_models import Secret
from tables.models.webhook_models import (
    LOCAL_ONLY_PROVIDERS,
    RealtimeChannel,
    TwilioChannel,
    WebhookTrigger,
)
from tables.serializers.base_serializers import WebhookTriggerNestedSerializer
from agents.models.agent_models import AgentDefinition
from tables.models.llm_models import RealtimeConfig, RealtimeTranscriptionConfig
from tables.models.realtime_models import (
    ConversationRecording,
    ElevenLabsRealtimeConfig,
    GeminiRealtimeConfig,
    OpenAIRealtimeConfig,
    RealtimeAgent,
    RealtimeAgentChat,
    RealtimeAgentDefinition,
    RealtimeSessionItem,
)
from tables.serializers.org_scoped_fields import (
    OrganizationScopedPrimaryKeyRelatedField,
    OrgScopedPrimaryKeyRelatedField,
)
from tables.services.secrets import secret_resolver


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


class RealtimeAgentDefinitionSerializer(serializers.ModelSerializer):
    # Org isolation: only configs/agent definitions from the caller's active
    # org may be referenced.
    agent_definition = OrganizationScopedPrimaryKeyRelatedField(
        queryset=AgentDefinition.objects.all()
    )
    # ElevenLabs uses a free-form voice id the frontend clears to '' when the
    # user hasn't entered one yet -- must accept blank, same as
    # RealtimeAgentWriteSerializer's identical override below.
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
        model = RealtimeAgentDefinition
        fields = "__all__"

    def validate(self, attrs):
        # `agent_definition` is this model's own primary key (a OneToOneField).
        # It is writable so `create()` can specify which AgentDefinition a new
        # row belongs to, but on `update()` it must never actually change: if
        # a caller ever sent a value different from the instance being
        # updated, `setattr()` + `instance.save()` would attempt an UPDATE
        # that affects 0 rows, and Django's save() silently falls back to an
        # INSERT — creating an orphan row while leaving the real target
        # completely untouched (looks exactly like "the update didn't save").
        # Reject the mismatch explicitly instead of allowing that silent
        # fallback.
        if self.instance is not None and "agent_definition" in attrs:
            new_agent_definition = attrs["agent_definition"]
            if new_agent_definition.pk != self.instance.pk:
                raise serializers.ValidationError(
                    {
                        "agent_definition": (
                            "agent_definition cannot be changed on an existing "
                            "RealtimeAgentDefinition; it is the record's own "
                            "identity (its primary key)."
                        )
                    }
                )

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
                "A RealtimeAgentDefinition may have at most one provider config "
                "set (openai_config, elevenlabs_config, or gemini_config)."
            )

        return attrs


class RealtimeSessionItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = RealtimeSessionItem
        fields = "__all__"


class RealtimeAgentChatSerializer(serializers.ModelSerializer):
    class Meta:
        model = RealtimeAgentChat
        fields = "__all__"


class OpenAIRealtimeConfigSerializer(serializers.ModelSerializer):
    api_key_secret_id = OrgScopedPrimaryKeyRelatedField(
        queryset=Secret.objects.all(),
        source="api_key_secret",
        required=False,
        allow_null=True,
    )
    transcription_api_key_secret_id = OrgScopedPrimaryKeyRelatedField(
        queryset=Secret.objects.all(),
        source="transcription_api_key_secret",
        required=False,
        allow_null=True,
    )

    class Meta:
        model = OpenAIRealtimeConfig
        fields = [
            "id",
            "custom_name",
            "api_key_secret_id",
            "model_name",
            "transcription_model_name",
            "transcription_api_key_secret_id",
            "voice_recognition_prompt",
            "org",
            "created_by",
        ]
        read_only_fields = ["org", "created_by"]


class ElevenLabsRealtimeConfigSerializer(serializers.ModelSerializer):
    api_key_secret_id = OrgScopedPrimaryKeyRelatedField(
        queryset=Secret.objects.all(),
        source="api_key_secret",
        required=False,
        allow_null=True,
    )

    class Meta:
        model = ElevenLabsRealtimeConfig
        fields = [
            "id",
            "custom_name",
            "api_key_secret_id",
            "model_name",
            "language",
            "org",
            "created_by",
        ]
        read_only_fields = ["org", "created_by"]


class GeminiRealtimeConfigSerializer(serializers.ModelSerializer):
    api_key_secret_id = OrgScopedPrimaryKeyRelatedField(
        queryset=Secret.objects.all(),
        source="api_key_secret",
        required=False,
        allow_null=True,
    )

    class Meta:
        model = GeminiRealtimeConfig
        fields = [
            "id",
            "custom_name",
            "api_key_secret_id",
            "model_name",
            "voice_recognition_prompt",
            "org",
            "created_by",
        ]
        read_only_fields = ["org", "created_by"]


class TwilioChannelSerializer(serializers.ModelSerializer):
    webhook_trigger = OrgScopedPrimaryKeyRelatedField(
        queryset=WebhookTrigger.objects.all(), required=False, allow_null=True
    )
    auth_token_secret_id = OrgScopedPrimaryKeyRelatedField(
        queryset=Secret.objects.all(),
        source="auth_token_secret",
        required=False,
        allow_null=True,
    )

    class Meta:
        model = TwilioChannel
        fields = [
            "channel",
            "account_sid",
            "auth_token_secret_id",
            "phone_number",
            "webhook_trigger",
        ]

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
        fields = ["channel", "account_sid", "auth_token_secret_id", "phone_number", "webhook_trigger"]


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
    `IsSystemApiKeyAuthenticated` (the trusted `realtime`/`voice_app` services only,
    never a logged-in user AND never a self-issued `key_type=USER` API key). That
    caller needs `auth_token` to validate the `X-Twilio-Signature` header on inbound
    Twilio webhook requests. Do NOT reuse this serializer for any user-facing
    endpoint

    `TwilioChannel.auth_token` is now a Secret reference (`auth_token_secret`), so
    it must be resolved at the point of use rather than read as a plain model
    attribute — a plain `ModelSerializer` field named "auth_token" would fail: the
    model no longer has that attribute.
    """

    auth_token = serializers.SerializerMethodField()

    class Meta(_TwilioChannelReadSerializer.Meta):
        fields = _TwilioChannelReadSerializer.Meta.fields + ["auth_token"]

    def get_auth_token(self, obj) -> str | None:
        if obj.auth_token_secret_id is None:
            return None
        return secret_resolver.resolve(
            secret_id=obj.auth_token_secret_id,
            org_id=obj.channel.org_id,
            context="TwilioChannel.auth_token",
        )


class RealtimeChannelInternalSerializer(RealtimeChannelSerializer):
    """Internal-only variant of `RealtimeChannelSerializer` used by `lookup_by_token`.

    Nests `_TwilioChannelInternalSerializer` so the response includes `twilio.auth_token`.
    Only ever instantiated behind `IsSystemApiKeyAuthenticated` — see
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
