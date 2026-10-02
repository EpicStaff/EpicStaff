from django.db import models

from tables.models.base_models import DefaultBaseModel


class DefaultModels(DefaultBaseModel):
    """Singleton that stores the default config instances shown to users in the frontend."""

    agent_llm_config = models.ForeignKey(
        "LLMConfig",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
        related_name="default_models_agent_llm",
    )
    agent_fcm_llm_config = models.ForeignKey(
        "LLMConfig",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
        related_name="default_models_agent_fcm_llm",
    )
    voice_llm_config = models.ForeignKey(
        "RealtimeConfig",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
        related_name="default_models_voice_llm",
    )
    transcription_llm_config = models.ForeignKey(
        "RealtimeTranscriptionConfig",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
        related_name="default_models_transcription_llm",
    )
    project_manager_llm_config = models.ForeignKey(
        "LLMConfig",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
        related_name="default_models_manager_llm",
    )
    memory_embedding_config = models.ForeignKey(
        "EmbeddingConfig",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
        related_name="default_models_memory_embedding",
    )
    memory_llm_config = models.ForeignKey(
        "LLMConfig",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
        related_name="default_models_memory_llm",
    )

    def __str__(self):
        return "Default Models"
