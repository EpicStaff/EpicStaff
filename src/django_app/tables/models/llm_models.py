from django.db import models
from rbac.models.last_edit import LastEditTrackedModel
from rbac.models.org_scoped import OrgScopedModel
from src.shared.system_one.constants import LLM_PROVIDER, OPENAI_PROVIDER, TYPESAFE_PROVIDER

from tables.models.tag_models import RealtimeConfigTag, RealtimeTranscriptionConfigTag


class SystemOneConfig(OrgScopedModel, LastEditTrackedModel, models.Model):
    """An organization's setup for one System One provider, used by CDT prompt entries of kind system_one.

    The database forbids only the other provider's fields; which fields a provider
    needs is checked when saving (SystemOneConfigSerializer) and when running (crew),
    so deleting a linked secret or LLM config clears the link instead of failing.
    """

    class Provider(models.TextChoices):
        TYPESAFE = TYPESAFE_PROVIDER, "TypeSafe"
        OPENAI = OPENAI_PROVIDER, "OpenAI"
        LLM = LLM_PROVIDER, "LLM"

    custom_name = models.TextField()
    provider = models.CharField(max_length=32, choices=Provider.choices)
    model_name = models.CharField(max_length=64, null=True, blank=True)
    api_key_secret = models.ForeignKey(
        "Secret",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="system_one_configs",
    )
    llm_config = models.ForeignKey(
        "ai_models.LLMConfig",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="system_one_configs",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(OrgScopedModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["org", "custom_name"],
                name="unique_systemoneconfig_name_per_org",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        provider__in=[TYPESAFE_PROVIDER, OPENAI_PROVIDER],
                        llm_config__isnull=True,
                    )
                    | models.Q(
                        provider=LLM_PROVIDER,
                        model_name__isnull=True,
                        api_key_secret__isnull=True,
                    )
                ),
                name="systemoneconfig_provider_fields",
            ),
        ]

    def __str__(self):
        return self.custom_name


# ---------------------------------------------------------------------------
# DEPRECATED: generic realtime model registry
# These tables are kept for backward compatibility with quickstart,
# import/export, and management commands, but are no longer used by the
# realtime agent flow. New agents use OpenAIRealtimeConfig,
# ElevenLabsRealtimeConfig, or GeminiRealtimeConfig from realtime_models.py.
# ---------------------------------------------------------------------------


class RealtimeModel(OrgScopedModel, models.Model):
    """DEPRECATED: use provider-specific config models in realtime_models.py."""

    name = models.CharField(max_length=250, default="gpt-4o-mini-realtime-preview-2024-12-17")
    provider = models.ForeignKey(
        "ai_models.Provider", on_delete=models.CASCADE, null=True, default=None
    )
    is_custom = models.BooleanField(default=False)

    class Meta(OrgScopedModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["org", "name", "provider"],
                name="unique_realtimemodel_name_provider_per_org",
            ),
            models.UniqueConstraint(
                fields=["name", "provider"],
                condition=models.Q(org__isnull=True),
                name="unique_realtimemodel_name_provider_builtin",
            ),
        ]


class RealtimeConfig(OrgScopedModel, models.Model):
    """DEPRECATED: use OpenAIRealtimeConfig / ElevenLabsRealtimeConfig / GeminiRealtimeConfig."""

    custom_name = models.CharField(max_length=250)
    realtime_model = models.ForeignKey("RealtimeModel", on_delete=models.CASCADE)
    api_key_secret = models.ForeignKey(
        "Secret",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="realtime_configs",
    )
    tags = models.ManyToManyField(RealtimeConfigTag, blank=True, related_name="realtime_configs")


class RealtimeTranscriptionModel(OrgScopedModel, models.Model):
    """DEPRECATED: transcription model is now a field inside OpenAIRealtimeConfig."""

    name = models.CharField(max_length=250, default="whisper-1")
    provider = models.ForeignKey(
        "ai_models.Provider", on_delete=models.CASCADE, null=True, default=None
    )
    is_custom = models.BooleanField(default=False)

    class Meta(OrgScopedModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["org", "name", "provider"],
                name="unique_realtimetranscriptionmodel_name_prov_per_org",
            ),
            models.UniqueConstraint(
                fields=["name", "provider"],
                condition=models.Q(org__isnull=True),
                name="unique_realtimetranscriptionmodel_name_prov_builtin",
            ),
        ]


class RealtimeTranscriptionConfig(OrgScopedModel, models.Model):
    """DEPRECATED: transcription config is now embedded in OpenAIRealtimeConfig."""

    custom_name = models.CharField(max_length=250)
    realtime_transcription_model = models.ForeignKey(
        "RealtimeTranscriptionModel", on_delete=models.CASCADE
    )
    api_key_secret = models.ForeignKey(
        "Secret",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="realtime_transcription_configs",
    )
    tags = models.ManyToManyField(
        RealtimeTranscriptionConfigTag,
        blank=True,
        related_name="realtime_transcription_configs",
    )
