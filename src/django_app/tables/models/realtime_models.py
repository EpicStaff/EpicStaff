from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from tables.models import AbstractDefaultFillableModel, DefaultBaseModel
from tables.models.rbac_models.org_scoped import OrgScopedModel


class AudioFormatChoices(models.TextChoices):
    PCM16 = "pcm16", "PCM 16-bit"
    g711_ulaw = "g711_ulaw", "G.711 u-law"
    g711_alaw = "g711_alaw", "G.711 a-law"


# ---------------------------------------------------------------------------
# Provider-specific realtime configuration models
# ---------------------------------------------------------------------------


class OpenAIRealtimeConfig(OrgScopedModel, models.Model):
    class Meta(OrgScopedModel.Meta):
        abstract = False
        db_table = "openai_realtime_config"

    custom_name = models.CharField(max_length=250)
    api_key = models.TextField(null=True, blank=True)
    model_name = models.CharField(max_length=250, default="gpt-realtime-1.5")
    transcription_model_name = models.CharField(
        max_length=250, default="whisper-1", null=True, blank=True
    )
    transcription_api_key = models.TextField(null=True, blank=True)
    voice_recognition_prompt = models.TextField(null=True, blank=True)

    def __str__(self):
        return self.custom_name


class ElevenLabsRealtimeConfig(OrgScopedModel, models.Model):
    class Meta(OrgScopedModel.Meta):
        abstract = False
        db_table = "elevenlabs_realtime_config"

    custom_name = models.CharField(max_length=250)
    api_key = models.TextField(null=True, blank=True)
    model_name = models.CharField(max_length=250, default="eleven_turbo_v2_5")
    language = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        help_text="ISO-639-1 language code, e.g. 'en'",
    )

    def __str__(self):
        return self.custom_name


class GeminiRealtimeConfig(OrgScopedModel, models.Model):
    class Meta(OrgScopedModel.Meta):
        abstract = False
        db_table = "gemini_realtime_config"

    custom_name = models.CharField(max_length=250)
    api_key = models.TextField(null=True, blank=True)
    model_name = models.CharField(
        max_length=250, default="gemini-3.1-flash-live-preview"
    )
    voice_recognition_prompt = models.TextField(null=True, blank=True)

    def __str__(self):
        return self.custom_name


# ---------------------------------------------------------------------------
# RealtimeAgent
# ---------------------------------------------------------------------------


class RealtimeAgent(AbstractDefaultFillableModel):
    class Meta:
        db_table = "realtime_agent"

    agent = models.OneToOneField(
        "Agent",
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="realtime_agent",
    )
    wake_word = models.CharField(max_length=255, null=True, blank=True)
    stop_prompt = models.CharField(
        default="stop", max_length=255, null=True, blank=True
    )
    voice = models.CharField(max_length=100, default="alloy")

    # Exactly one of these should be non-null; enforced in clean()
    openai_config = models.ForeignKey(
        "OpenAIRealtimeConfig",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
        related_name="realtime_agents",
    )
    elevenlabs_config = models.ForeignKey(
        "ElevenLabsRealtimeConfig",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
        related_name="realtime_agents",
    )
    gemini_config = models.ForeignKey(
        "GeminiRealtimeConfig",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
        related_name="realtime_agents",
    )

    def clean(self):
        set_count = sum(
            [
                self.openai_config_id is not None,
                self.elevenlabs_config_id is not None,
                self.gemini_config_id is not None,
            ]
        )
        if set_count > 1:
            raise ValidationError(
                "A RealtimeAgent may have at most one provider config set "
                "(openai_config, elevenlabs_config, or gemini_config)."
            )

    @property
    def active_provider_config(self):
        """Return whichever provider config FK is set, or None."""
        return self.openai_config or self.elevenlabs_config or self.gemini_config

    @property
    def provider_name(self) -> str | None:
        """Return 'openai', 'elevenlabs', 'gemini', or None."""
        if self.openai_config_id is not None:
            return "openai"
        if self.elevenlabs_config_id is not None:
            return "elevenlabs"
        if self.gemini_config_id is not None:
            return "gemini"
        return None

    def save(self, *args, **kwargs):
        if self.wake_word is None:
            if self.agent.role is not None:
                self.wake_word = self.agent.role
            else:
                self.wake_word = "agent"
        super().save(*args, **kwargs)

    def get_default_model(self):
        return DefaultRealtimeAgentConfig.load()


# ---------------------------------------------------------------------------
# RealtimeAgentChat  (session snapshot)
# ---------------------------------------------------------------------------
class RealtimeAgentDefinition(AbstractDefaultFillableModel):
    class Meta:
        db_table = "realtime_agent_definition"

    agent_definition = models.OneToOneField(
        "agents.AgentDefinition",
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="realtime_agent",
    )
    wake_word = models.CharField(max_length=255, null=True, blank=True)
    stop_prompt = models.CharField(
        default="stop", max_length=255, null=True, blank=True
    )
    language = models.CharField(
        max_length=2, null=True, blank=True, help_text="ISO-639-1 format"
    )
    voice_recognition_prompt = models.TextField(
        null=True,
        blank=True,
        help_text="The prompt to use for the transcription, to guide the model (e.g. 'Expect words related to technology')",
    )
    voice = models.CharField(max_length=100, default="alloy")
    realtime_config = models.ForeignKey(
        "RealtimeConfig", on_delete=models.SET_NULL, null=True, default=None
    )
    realtime_transcription_config = models.ForeignKey(
        "RealtimeTranscriptionConfig",
        on_delete=models.SET_NULL,
        null=True,
        default=None,
    )

    def save(self, *args, **kwargs):
        if self.wake_word is None:
            if self.agent_definition.name is not None:
                self.wake_word = self.agent_definition.name
            else:
                self.wake_word = "agent"

        super().save(*args, **kwargs)

    def get_default_model(self):
        return DefaultRealtimeAgentConfig.load()


class RealtimeAgentChat(models.Model):
    class EndReason(models.TextChoices):
        COMPLETED = "completed", "Completed"
        ERROR = "error", "Error"
        CANCELLED = "cancelled", "Cancelled"
        TIMEOUT = "timeout", "Timeout"

    class Meta:
        db_table = "realtime_agent_chat"

    rt_agent = models.ForeignKey(
        "RealtimeAgent",
        on_delete=models.SET_NULL,
        null=True,
    )
    rt_agent_definition = models.ForeignKey(
        "RealtimeAgentDefinition",
        on_delete=models.SET_NULL,
        null=True,
        default=None,
    )
    connection_key = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.FloatField(null=True, blank=True)
    end_reason = models.CharField(
        max_length=20,
        choices=EndReason.choices,
        null=True,
        blank=True,
    )

    # Generic snapshot fields (always filled)
    wake_word = models.CharField(max_length=255, null=True, blank=True)
    stop_prompt = models.CharField(
        max_length=255, null=True, blank=True, default="stop"
    )
    voice = models.CharField(max_length=100, default="alloy")

    # Provider-specific snapshot text fields (null when not applicable)
    language = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        help_text="ElevenLabs: ISO-639-1 language code",
    )
    voice_recognition_prompt = models.TextField(
        null=True, blank=True, help_text="OpenAI / Gemini: transcription hint"
    )
    input_audio_format = models.CharField(
        max_length=20,
        choices=AudioFormatChoices.choices,
        default=AudioFormatChoices.PCM16,
    )
    output_audio_format = models.CharField(
        max_length=20,
        choices=AudioFormatChoices.choices,
        default=AudioFormatChoices.PCM16,
    )

    # Config FK snapshot (only one non-null per session)
    openai_config = models.ForeignKey(
        "OpenAIRealtimeConfig",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
    )
    elevenlabs_config = models.ForeignKey(
        "ElevenLabsRealtimeConfig",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
    )
    gemini_config = models.ForeignKey(
        "GeminiRealtimeConfig",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
    )


# ---------------------------------------------------------------------------
# ConversationRecording
# ---------------------------------------------------------------------------


class ConversationRecording(models.Model):
    class RecordingType(models.TextChoices):
        INBOUND = "inbound", "Inbound (user audio)"
        OUTBOUND = "outbound", "Outbound (agent audio)"

    class Meta:
        db_table = "conversation_recording"

    rt_agent_chat = models.ForeignKey(
        "RealtimeAgentChat",
        on_delete=models.CASCADE,
        related_name="recordings",
    )
    file = models.FileField(upload_to="recordings/%Y/%m/%d/")
    recording_type = models.CharField(max_length=20, choices=RecordingType.choices)
    audio_format = models.CharField(max_length=10, default="wav")
    duration_seconds = models.FloatField(null=True, blank=True)
    file_size = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.rt_agent_chat_id}/{self.recording_type}"


# ---------------------------------------------------------------------------
# RealtimeSessionItem
# ---------------------------------------------------------------------------


class RealtimeSessionItem(models.Model):
    class Meta:
        db_table = "realtime_session_items"

    connection_key = models.TextField()
    data = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)


# ---------------------------------------------------------------------------
# DefaultRealtimeAgentConfig  (singleton defaults — mirrors simplified RealtimeAgent)
# ---------------------------------------------------------------------------


class DefaultRealtimeAgentConfig(DefaultBaseModel):
    class Meta:
        db_table = "default_realtime_agent_config"

    wake_word = models.CharField(max_length=255, null=True, blank=True)
    stop_prompt = models.CharField(
        default="stop", max_length=255, null=True, blank=True
    )
    voice = models.CharField(max_length=100, default="alloy")

    def __str__(self):
        return "Default Realtime Agent Config"
