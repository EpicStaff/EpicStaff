from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from tables.models import (
    DefaultBaseModel,
    Provider,
    AbstractDefaultFillableModel,
)
from tables.models.tag_models import (
    LLMModelTag,
    LLMConfigTag,
    RealtimeConfigTag,
    RealtimeTranscriptionConfigTag,
)
from tables.models.rbac_models.org_scoped import OrgScopedModel


class LLMModel(OrgScopedModel, models.Model):
    name = models.TextField()
    predefined = models.BooleanField(default=False)
    description = models.TextField(null=True, blank=True)
    llm_provider = models.ForeignKey(Provider, on_delete=models.SET_NULL, null=True)
    deployment_id = models.TextField(
        null=True, blank=True, help_text="Azure Deployment Name or Watsonx ID"
    )
    api_version = models.TextField(null=True, blank=True)
    base_url = models.TextField(null=True, blank=True)
    is_visible = models.BooleanField(default=True)
    is_custom = models.BooleanField(default=False)
    tags = models.ManyToManyField(LLMModelTag, blank=True, related_name="llm_models")

    class Meta(OrgScopedModel.Meta):
        unique_together = (
            "name",
            "llm_provider",
        )

    def __str__(self):
        return self.name


class DefaultLLMConfig(DefaultBaseModel):
    model = models.ForeignKey(LLMModel, on_delete=models.SET_NULL, null=True)
    temperature = models.FloatField(default=0.7, null=True, blank=True)
    top_p = models.FloatField(null=True, blank=True)
    stop = models.JSONField(null=True, blank=True)
    max_tokens = models.IntegerField(
        default=4096,
        null=True,
        blank=True,
        validators=[MinValueValidator(500)],
    )
    presence_penalty = models.FloatField(null=True, blank=True)
    frequency_penalty = models.FloatField(null=True, blank=True)
    logit_bias = models.JSONField(null=True, blank=True)
    seed = models.IntegerField(null=True, blank=True)
    logprobs = models.BooleanField(null=True, blank=True)
    top_logprobs = models.IntegerField(null=True, blank=True)
    base_url = models.TextField(null=True, blank=True)
    api_version = models.TextField(null=True, blank=True)
    headers = models.JSONField(default=dict, blank=True)
    extra_headers = models.JSONField(default=dict, blank=True)
    timeout = models.FloatField(null=True, blank=True)
    is_visible = models.BooleanField(default=True)


class LLMConfig(OrgScopedModel, AbstractDefaultFillableModel):
    custom_name = models.TextField()
    model = models.ForeignKey(LLMModel, on_delete=models.CASCADE, null=True)
    temperature = models.FloatField(
        default=0.5,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(0.0),
            MaxValueValidator(2.0),
        ],
    )
    top_p = models.FloatField(default=1.0, null=True, blank=True)
    stop = models.JSONField(null=True, blank=True)
    max_tokens = models.IntegerField(
        default=4096, null=True, blank=True, validators=[MinValueValidator(500)]
    )
    presence_penalty = models.FloatField(default=0.0, null=True, blank=True)
    frequency_penalty = models.FloatField(default=0.0, null=True, blank=True)
    logit_bias = models.JSONField(null=True, blank=True)
    seed = models.IntegerField(null=True, blank=True)
    logprobs = models.BooleanField(null=True, blank=True)
    top_logprobs = models.IntegerField(null=True, blank=True)
    base_url = models.TextField(null=True, blank=True)
    api_version = models.TextField(null=True, blank=True)
    api_key_secret = models.ForeignKey(
        "Secret",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="llm_configs",
    )
    headers = models.JSONField(default=dict, blank=True)
    extra_headers = models.JSONField(default=dict, blank=True)
    timeout = models.FloatField(default=120.0, null=True, blank=True)
    is_visible = models.BooleanField(default=True)
    tags = models.ManyToManyField(LLMConfigTag, blank=True, related_name="llm_configs")

    class Meta(OrgScopedModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["org", "custom_name"],
                name="unique_llmconfig_name_per_org",
            ),
        ]

    def get_default_model(self):
        return DefaultLLMConfig.load()

    def delete(self, *args, **kwargs):
        from tables.models import set_field_value_null_in_tool_configs
        from tables.models import ToolConfigField

        llm_config_id = self.pk
        result = super().delete(*args, **kwargs)

        set_field_value_null_in_tool_configs(
            field_type=ToolConfigField.FieldType.LLM_CONFIG, value=llm_config_id
        )
        return result


# ---------------------------------------------------------------------------
# DEPRECATED: generic realtime model registry
# These tables are kept for backward compatibility with quickstart,
# import/export, and management commands, but are no longer used by the
# realtime agent flow. New agents use OpenAIRealtimeConfig,
# ElevenLabsRealtimeConfig, or GeminiRealtimeConfig from realtime_models.py.
# ---------------------------------------------------------------------------

class RealtimeModel(OrgScopedModel, models.Model):
    """DEPRECATED: use provider-specific config models in realtime_models.py."""

    name = models.CharField(
        max_length=250, default="gpt-4o-mini-realtime-preview-2024-12-17"
    )
    provider = models.ForeignKey(
        "Provider", on_delete=models.CASCADE, null=True, default=None
    )
    is_custom = models.BooleanField(default=False)


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
    tags = models.ManyToManyField(
        RealtimeConfigTag, blank=True, related_name="realtime_configs"
    )


class RealtimeTranscriptionModel(OrgScopedModel, models.Model):
    """DEPRECATED: transcription model is now a field inside OpenAIRealtimeConfig."""

    name = models.CharField(max_length=250, default="whisper-1")
    provider = models.ForeignKey(
        "Provider", on_delete=models.CASCADE, null=True, default=None
    )
    is_custom = models.BooleanField(default=False)


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
