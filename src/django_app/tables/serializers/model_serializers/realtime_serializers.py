from contextlib import contextmanager

from agents.models.agent_models import AgentDefinition
from ai_models.domain.specs import ModelKind
from ai_models.repository import CatalogRepository
from django.conf import settings
from django.core.validators import RegexValidator
from rbac.authorship import (
    OMIT_AUTHORSHIP_CONTEXT_KEY,
    AuthorStampingSerializerMixin,
    AuthorSummarySerializerMixin,
    LastEditFieldsSerializerMixin,
)
from rbac.scoping.fields import OrgScopedPrimaryKeyRelatedField, OrgScopedUniqueValidator
from rest_framework import serializers
from tables.exceptions import TwilioUnavailableError
from tables.models.base_models import SOFT_DELETE_FIELD_NAMES
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
from tables.models.secret_models import Secret
from tables.models.webhook_models import (
    LOCAL_ONLY_PROVIDERS,
    RealtimeChannel,
    TwilioChannel,
    WebhookTrigger,
    WebhookTriggerAuthKind,
)
from tables.serializers.base_serializer import OpenAIRealtimeModelNameValidationMixin
from tables.serializers.base_serializers import WebhookTriggerNestedSerializer
from tables.serializers.utils.soft_delete_fields import (
    ExcludeSoftDeleteFieldsMixin,
    KeptLinkPrimaryKeyRelatedField,
)
from tables.services.secrets import secret_resolver
from tables.services.twilio_service import (
    PhoneNumberClaimRefusal,
    TwilioNoAnswerError,
    TwilioPhoneNumberClaimError,
    TwilioService,
)


class RealtimeAgentDefinitionSerializer(serializers.ModelSerializer):
    # Org isolation: only configs/agent definitions from the caller's active
    # org may be referenced.
    agent_definition = OrgScopedPrimaryKeyRelatedField(queryset=AgentDefinition.objects.all())
    # ElevenLabs uses a free-form voice id the frontend clears to '' when the
    # user hasn't entered one yet -- must accept blank, same as
    # RealtimeAgentWriteSerializer's identical override below.
    voice = serializers.CharField(allow_blank=True, max_length=100, default="alloy")
    language = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        validators=[
            RegexValidator(
                r"^[a-z]{2}$",
                message="Language must be a lowercase ISO-639-1 code, e.g. 'en'.",
            )
        ],
    )
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
        exclude = SOFT_DELETE_FIELD_NAMES

    def validate_language(self, value):
        return value or None

    def validate(self, attrs):
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

        openai_config = attrs.get("openai_config", getattr(self.instance, "openai_config", None))
        elevenlabs_config = attrs.get(
            "elevenlabs_config", getattr(self.instance, "elevenlabs_config", None)
        )
        gemini_config = attrs.get("gemini_config", getattr(self.instance, "gemini_config", None))

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


class RealtimeSessionItemSerializer(AuthorSummarySerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = RealtimeSessionItem
        fields = "__all__"


class RealtimeAgentChatSerializer(serializers.ModelSerializer):
    class Meta:
        model = RealtimeAgentChat
        fields = "__all__"


class OpenAIRealtimeConfigSerializer(
    AuthorStampingSerializerMixin,
    LastEditFieldsSerializerMixin,
    OpenAIRealtimeModelNameValidationMixin,
    serializers.ModelSerializer,
):
    api_key_secret_id = KeptLinkPrimaryKeyRelatedField(
        queryset=Secret.all_objects.all(),
        source="api_key_secret",
        required=False,
        allow_null=True,
    )
    transcription_api_key_secret_id = KeptLinkPrimaryKeyRelatedField(
        queryset=Secret.all_objects.all(),
        source="transcription_api_key_secret",
        required=False,
        allow_null=True,
    )

    custom_name = serializers.CharField(
        max_length=250,
        validators=[
            OrgScopedUniqueValidator(
                queryset=OpenAIRealtimeConfig.objects.all(),
                message="An OpenAI realtime config with this name already exists.",
            )
        ],
    )

    class Meta:
        model = OpenAIRealtimeConfig
        fields = [
            "id",
            "custom_name",
            "api_key_secret_id",
            "model_name",
            "base_url",
            "transcription_model_name",
            "transcription_api_key_secret_id",
            "voice_recognition_prompt",
            "org",
            "created_by",
            "created_at",
        ]
        read_only_fields = ["org", "created_by", "created_at"]

    def validate_transcription_model_name(self, value):
        # An unchanged stored name is kept, so a model that left the catalog never
        # blocks editing the rest of the config.
        if value is None or (self.instance and value == self.instance.transcription_model_name):
            return value
        if CatalogRepository.default().model(ModelKind.TRANSCRIPTION, "openai", value) is None:
            raise serializers.ValidationError(f"'{value}' is not an OpenAI transcription model.")
        return value


class ElevenLabsRealtimeConfigSerializer(
    AuthorStampingSerializerMixin,
    LastEditFieldsSerializerMixin,
    serializers.ModelSerializer,
):
    api_key_secret_id = KeptLinkPrimaryKeyRelatedField(
        queryset=Secret.all_objects.all(),
        source="api_key_secret",
        required=False,
        allow_null=True,
    )

    custom_name = serializers.CharField(
        max_length=250,
        validators=[
            OrgScopedUniqueValidator(
                queryset=ElevenLabsRealtimeConfig.objects.all(),
                message="An ElevenLabs realtime config with this name already exists.",
            )
        ],
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
            "created_at",
        ]
        read_only_fields = ["org", "created_by", "created_at"]


class GeminiRealtimeConfigSerializer(
    AuthorStampingSerializerMixin,
    LastEditFieldsSerializerMixin,
    serializers.ModelSerializer,
):
    api_key_secret_id = KeptLinkPrimaryKeyRelatedField(
        queryset=Secret.all_objects.all(),
        source="api_key_secret",
        required=False,
        allow_null=True,
    )

    custom_name = serializers.CharField(
        max_length=250,
        validators=[
            OrgScopedUniqueValidator(
                queryset=GeminiRealtimeConfig.objects.all(),
                message="A Gemini realtime config with this name already exists.",
            )
        ],
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
            "created_at",
        ]
        read_only_fields = ["org", "created_by", "created_at"]


class TwilioAuthTokenSecretSerializer(serializers.Serializer):
    """A client-supplied Twilio auth-token Secret id, scoped to the active org.

    Another org's id is rejected exactly like an unknown one, so existence never leaks.
    """

    auth_token_secret_id = OrgScopedPrimaryKeyRelatedField(queryset=Secret.objects.all())


# The request field each refusal is reported on: the input the user has to fix.
_PHONE_NUMBER_CLAIM_REFUSAL_FIELDS = {
    PhoneNumberClaimRefusal.NOT_E164: "phone_number",
    PhoneNumberClaimRefusal.INVALID_ACCOUNT_SID: "account_sid",
    PhoneNumberClaimRefusal.NO_AUTH_TOKEN: "auth_token_secret_id",
    PhoneNumberClaimRefusal.AUTH_TOKEN_UNAVAILABLE: "auth_token_secret_id",
    PhoneNumberClaimRefusal.CREDENTIALS_REJECTED: "account_sid",
    PhoneNumberClaimRefusal.NOT_IN_ACCOUNT: "phone_number",
    PhoneNumberClaimRefusal.ALREADY_USED: "phone_number",
}


@contextmanager
def _phone_number_claim_error_as_field_error():
    try:
        yield
    except TwilioPhoneNumberClaimError as error:
        field = _PHONE_NUMBER_CLAIM_REFUSAL_FIELDS[error.reason]
        raise serializers.ValidationError({field: [error.message]}) from None
    except TwilioNoAnswerError as error:
        raise TwilioUnavailableError(error.message) from error


class TwilioChannelSerializer(serializers.ModelSerializer):
    """Writes a channel's Twilio settings; a new phone number must be in its Twilio account.

    The number is checked at save time, after the viewset's org, permission and secret
    Use checks, by `TwilioService.claim_phone_number`: it proves ownership before
    uniqueness, so a caller can't learn whether another org holds a number.
    """

    webhook_trigger = KeptLinkPrimaryKeyRelatedField(
        queryset=WebhookTrigger.all_objects.all(), required=False, allow_null=True
    )
    auth_token_secret_id = KeptLinkPrimaryKeyRelatedField(
        queryset=Secret.all_objects.all(),
        source="auth_token_secret",
        required=True,
        allow_null=False,
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
        # No UniqueValidator from the live-number constraint: it would answer "taken"
        # before ownership is proven.
        extra_kwargs = {"phone_number": {"validators": []}}

    def validate(self, attrs):
        attrs = super().validate(attrs)

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

        auth = getattr(wt, "auth", None) if wt else None
        if auth is not None and auth.kind not in (WebhookTriggerAuthKind.TWILIO,):
            raise serializers.ValidationError(
                {
                    "webhook_trigger": (
                        f"This trigger's auth is already configured for "
                        f"kind='{auth.kind}' and cannot be claimed by a "
                        "Twilio channel."
                    )
                }
            )

        return attrs

    def validate_phone_number(self, value):
        # A blank number is no number: "" would otherwise be one more unique live value.
        return value or None

    def create(self, validated_data):
        with _phone_number_claim_error_as_field_error(), self._claim_phone_number(validated_data):
            return super().create(validated_data)

    def update(self, instance, validated_data):
        with _phone_number_claim_error_as_field_error(), self._claim_phone_number(validated_data):
            return super().update(instance, validated_data)

    def _claim_phone_number(self, validated_data):
        # A partial update leaves out what it doesn't change: fall back to the stored values.
        instance = self.instance
        return TwilioService().claim_phone_number(
            channel=validated_data.get("channel", getattr(instance, "channel", None)),
            account_sid=validated_data.get("account_sid", getattr(instance, "account_sid", "")),
            auth_token_secret=validated_data.get(
                "auth_token_secret", getattr(instance, "auth_token_secret", None)
            ),
            phone_number=validated_data.get("phone_number"),
            current_phone_number=getattr(instance, "phone_number", None),
        )


class _TwilioChannelReadSerializer(serializers.ModelSerializer):
    """Read-only variant that expands webhook_trigger so downstream consumers get live_url."""

    webhook_trigger = WebhookTriggerNestedSerializer(read_only=True)

    class Meta:
        model = TwilioChannel
        fields = [
            "channel",
            "account_sid",
            "auth_token_secret_id",
            "phone_number",
            "webhook_trigger",
        ]


class RealtimeChannelSerializer(
    ExcludeSoftDeleteFieldsMixin,
    AuthorStampingSerializerMixin,
    LastEditFieldsSerializerMixin,
    serializers.ModelSerializer,
):
    twilio = _TwilioChannelReadSerializer(read_only=True)
    # Legacy pointer at the removed staff-agent API surface (`RealtimeAgent`).
    # Kept read-only, never writable: the only supported destination going
    # forward is `realtime_agent_definition`. It stays in the response so
    # operators can see which rows on this org are still stranded on the old
    # destination. It cannot be dropped from the model because migrations are
    # frozen on this branch.
    realtime_agent = serializers.PrimaryKeyRelatedField(read_only=True)
    realtime_agent_definition = OrgScopedPrimaryKeyRelatedField(
        queryset=RealtimeAgentDefinition.objects.all(),
        org_lookup="agent_definition__org_id",
        required=False,
        allow_null=True,
    )

    class Meta:
        model = RealtimeChannel
        fields = "__all__"
        read_only_fields = ["org", "created_by", "created_at"]

    def validate(self, attrs):
        # `realtime_agent` is read-only, so a caller can no longer set both
        # destinations at once. But a row created on `main` before this field
        # existed may already carry a legacy `realtime_agent` in the DB — for
        # such a stranded row, setting `realtime_agent_definition` is the fix,
        # not a conflict. Let the new destination win and clear the dead
        # pointer, rather than rejecting the very repair the caller is making.
        if "realtime_agent_definition" in attrs:
            attrs["realtime_agent"] = None

        return attrs


class _WebhookTriggerInternalSerializer(WebhookTriggerNestedSerializer):
    """`WebhookTriggerNestedSerializer` without its author, for `lookup_by_token`.

    Rendered without authorship, `created_by` would still be the author's plain id;
    the realtime service is sent no user ids, so the field is left out.
    """

    class Meta(WebhookTriggerNestedSerializer.Meta):
        fields = [
            field for field in WebhookTriggerNestedSerializer.Meta.fields if field != "created_by"
        ]


class _TwilioChannelInternalSerializer(_TwilioChannelReadSerializer):
    """Internal-only variant of `_TwilioChannelReadSerializer` that includes `auth_token`.

    Used exclusively by `RealtimeChannelViewSet.lookup_by_token`, which is gated by
    `IsSystemApiKeyAuthenticated` (the trusted `realtime` service only,
    never a logged-in user AND never a self-issued `key_type=USER` API key). That
    caller needs `auth_token` to validate the `X-Twilio-Signature` header on inbound
    Twilio webhook requests. Do NOT reuse this serializer for any user-facing
    endpoint

    `TwilioChannel.auth_token` is now a Secret reference (`auth_token_secret`), so
    it is resolved and sealed with the transport key for the realtime service rather
    than read as a plain model attribute; a plain `ModelSerializer` field named
    "auth_token" would fail: the model no longer has that attribute.
    """

    webhook_trigger = _WebhookTriggerInternalSerializer(read_only=True)
    auth_token = serializers.SerializerMethodField()

    class Meta(_TwilioChannelReadSerializer.Meta):
        fields = [*_TwilioChannelReadSerializer.Meta.fields, "auth_token"]

    def get_auth_token(self, obj) -> str | None:
        if obj.auth_token_secret_id is None:
            return None
        return secret_resolver.resolve_sealed(
            secret_id=obj.auth_token_secret_id,
            org_id=obj.channel.org_id,
            context="TwilioChannel.auth_token",
        )


class RealtimeChannelInternalSerializer(RealtimeChannelSerializer):
    """Internal-only variant of `RealtimeChannelSerializer` used by `lookup_by_token`.

    Nests `_TwilioChannelInternalSerializer` so the response includes `twilio.auth_token`.
    Only ever instantiated behind `IsSystemApiKeyAuthenticated` — see
    `RealtimeChannelViewSet.lookup_by_token`. Rendered without authorship, nested rows
    included: the realtime service never reads it, so no user ids, names or avatars are
    sent there and rendering queries no user or last edit.
    """

    twilio = _TwilioChannelInternalSerializer(read_only=True)

    class Meta(RealtimeChannelSerializer.Meta):
        fields = None
        exclude = ["created_by"]

    def __init__(self, *args, **kwargs):
        kwargs["context"] = {**kwargs.get("context", {}), OMIT_AUTHORSHIP_CONTEXT_KEY: True}
        super().__init__(*args, **kwargs)


def _has_wav_header(file) -> bool:
    file.seek(0)
    prefix = file.read(12)
    # Left at its start, as the upload handler hands it over, for whatever reads it next.
    file.seek(0)
    # A WAV file opens with b"RIFF", a 4-byte chunk size, then b"WAVE".
    return prefix[:4] == b"RIFF" and prefix[8:12] == b"WAVE"


class ConversationRecordingSerializer(serializers.ModelSerializer):
    # The realtime service, the only creator, knows its chat only by connection_key.
    connection_key = serializers.CharField(write_only=True)

    class Meta:
        model = ConversationRecording
        fields = "__all__"
        read_only_fields = ["rt_agent_chat", "file_size", "audio_format", "created_at"]

    def validate_file(self, file):
        """Accept only a WAV file of at most MAX_VOICE_RECORDING_SIZE bytes."""
        if file.size > settings.MAX_VOICE_RECORDING_SIZE:
            raise serializers.ValidationError(
                f"A recording may be at most {settings.MAX_VOICE_RECORDING_SIZE} bytes."
            )
        if not _has_wav_header(file):
            raise serializers.ValidationError("A recording must be a WAV file.")
        return file

    def validate(self, attrs):
        """Resolve connection_key to the recording's chat.

        Here, before saving: an unknown key found only at save time would leave the file
        written and no row to delete it.
        """
        connection_key = attrs.pop("connection_key")
        try:
            attrs["rt_agent_chat"] = RealtimeAgentChat.objects.get(connection_key=connection_key)
        except RealtimeAgentChat.DoesNotExist as error:
            raise serializers.ValidationError(
                {"connection_key": "No matching RealtimeAgentChat found"}
            ) from error
        return attrs


class RealtimeAgentReadSerializer(serializers.ModelSerializer):
    openai_config = OpenAIRealtimeConfigSerializer(read_only=True)
    elevenlabs_config = ElevenLabsRealtimeConfigSerializer(read_only=True)
    gemini_config = GeminiRealtimeConfigSerializer(read_only=True)

    class Meta:
        model = RealtimeAgent
        exclude = ["agent"]


class RealtimeAgentWriteSerializer(serializers.ModelSerializer):
    voice = serializers.CharField(allow_blank=True, max_length=100, default="alloy")
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
        openai_config = attrs.get("openai_config", getattr(self.instance, "openai_config", None))
        elevenlabs_config = attrs.get(
            "elevenlabs_config", getattr(self.instance, "elevenlabs_config", None)
        )
        gemini_config = attrs.get("gemini_config", getattr(self.instance, "gemini_config", None))

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
