from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from tables.models import (
    DefaultBaseModel,
    Provider,
    AbstractDefaultFillableModel,
)
from tables.models.tag_models import LLMModelTag


class LLMModel(models.Model):
    name = models.TextField()
    predefined = models.BooleanField(default=False)
    description = models.TextField(null=True, blank=True)
    llm_provider = models.ForeignKey(Provider, on_delete=models.SET_NULL, null=True)
    base_url = models.URLField(null=True, blank=True)
    deployment_id = models.TextField(
        null=True, blank=True, help_text="Azure Deployment Name or Watsonx ID"
    )
    api_version = models.TextField(null=True, blank=True)
    is_visible = models.BooleanField(default=True)
    is_custom = models.BooleanField(default=False)
    tags = models.ManyToManyField(LLMModelTag, blank=True, related_name="llm_models")

    class Meta:
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
    response_format = models.JSONField(null=True, blank=True)
    seed = models.IntegerField(null=True, blank=True)
    api_key = models.TextField(null=True, blank=True)
    headers = models.JSONField(default=dict, blank=True)
    extra_headers = models.JSONField(default=dict, blank=True)
    timeout = models.FloatField(null=True, blank=True)
    is_visible = models.BooleanField(default=True)


class LLMConfig(AbstractDefaultFillableModel):
    custom_name = models.TextField(unique=True)
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
    response_format = models.JSONField(null=True, blank=True)
    seed = models.IntegerField(null=True, blank=True, default=42)
    api_key = models.TextField(null=True, blank=True)
    headers = models.JSONField(default=dict, blank=True)
    extra_headers = models.JSONField(default=dict, blank=True)
    timeout = models.FloatField(default=120.0, null=True, blank=True)
    is_visible = models.BooleanField(default=True)

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


class RealtimeModel(models.Model):
    name = models.CharField(
        max_length=250, default="gpt-4o-mini-realtime-preview-2024-12-17"
    )
    provider = models.ForeignKey(
        "Provider", on_delete=models.CASCADE, null=True, default=None
    )
    is_custom = models.BooleanField(default=False)


class RealtimeConfig(models.Model):
    custom_name = models.CharField(max_length=250)
    realtime_model = models.ForeignKey("RealtimeModel", on_delete=models.CASCADE)
    api_key = models.TextField(null=True, blank=True)


class RealtimeTranscriptionModel(models.Model):
    name = models.CharField(max_length=250, default="whisper-1")
    provider = models.ForeignKey(
        "Provider", on_delete=models.CASCADE, null=True, default=None
    )
    is_custom = models.BooleanField(default=False)


class RealtimeTranscriptionConfig(models.Model):
    custom_name = models.CharField(max_length=250)
    realtime_transcription_model = models.ForeignKey(
        "RealtimeTranscriptionModel", on_delete=models.CASCADE
    )
    api_key = models.TextField(null=True, blank=True)
