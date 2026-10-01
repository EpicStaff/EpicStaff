from django.db import models
from rbac.models.org_scoped import OrgScopedModel


class DefaultModels(OrgScopedModel):
    """Per-organization row that stores the default config instances shown to users in the frontend."""

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

    class Meta(OrgScopedModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["org"], name="unique_defaultmodels_per_org"),
        ]

    @classmethod
    def load_for_org(cls, org_id: int) -> "DefaultModels":
        """Return the organization's default models row, creating an empty one on first access.

        Not cached per process: the `DefaultBaseModel` class-keyed cache would
        serve one organization's row to another.
        """
        default_models, _ = cls.objects.get_or_create(org_id=org_id)
        return default_models

    def __str__(self):
        return "Default Models"
