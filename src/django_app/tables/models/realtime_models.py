from django.db import models
from django.utils import timezone

from tables.models import AbstractDefaultFillableModel, DefaultBaseModel


class VoiceChoices(models.TextChoices):
    ALLOY = "alloy", "Alloy"
    AHS = "ash", "Ash"
    BALLAD = "ballad", "Ballad"
    CORAL = "coral", "Coral"
    ECHO = "echo", "Echo"
    FABLE = "fable", "Fable"
    ONYX = "onyx", "Onyx"
    NOVA = "nova", "Nova"
    SAGE = "sage", "Sage"
    SHIMMER = "shimmer", "Shimmer"
    VERSE = "verse", "Verse"


class AudioFormatChoices(models.TextChoices):
    PCM16 = "pcm16", "PCM 16-bit"
    g711_ulaw = "g711_ulaw", "G.711 u-law"
    g711_alaw = "g711_alaw", "G.711 a-law"


# AbstractDefaultFillableModel
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
    language = models.CharField(
        max_length=2, null=True, blank=True, help_text="ISO-639-1 format"
    )
    voice_recognition_prompt = models.TextField(
        null=True,
        blank=True,
        help_text="The prompt to use for the transcription, to guide the model (e.g. 'Expect words related to technology')",
    )
    voice = models.CharField(max_length=100, default=VoiceChoices.ALLOY)
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
            if self.agent.role is not None:
                self.wake_word = self.agent.role
            else:
                self.wake_word = "agent"

        super().save(*args, **kwargs)

    def get_default_model(self):
        return DefaultRealtimeAgentConfig.load()


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
    voice = models.CharField(max_length=100, default=VoiceChoices.ALLOY)
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
    voice = models.CharField(max_length=100, default=VoiceChoices.ALLOY)
    realtime_config = models.ForeignKey(
        "RealtimeConfig", on_delete=models.SET_NULL, null=True, default=None
    )
    realtime_transcription_config = models.ForeignKey(
        "RealtimeTranscriptionConfig",
        on_delete=models.SET_NULL,
        null=True,
        default=None,
    )
    created_at = models.DateTimeField(default=timezone.now)

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


class RealtimeSessionItem(models.Model):
    class Meta:
        db_table = "realtime_session_items"

    connection_key = models.TextField()
    data = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)


class DefaultRealtimeAgentConfig(DefaultBaseModel):
    class Meta:
        db_table = "default_realtime_agent_config"

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
    voice = models.CharField(max_length=100, default=VoiceChoices.ALLOY)
    realtime_config = models.ForeignKey(
        "RealtimeConfig", on_delete=models.SET_NULL, null=True, default=None
    )
    realtime_transcription_config = models.ForeignKey(
        "RealtimeTranscriptionConfig",
        on_delete=models.SET_NULL,
        null=True,
        default=None,
    )

    def __str__(self):
        return "Default Realtime Agent Config"
