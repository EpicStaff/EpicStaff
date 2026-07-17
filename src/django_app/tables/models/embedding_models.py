from django.db import models
from tables.models.tag_models import EmbeddingModelTag, EmbeddingConfigTag
from tables.models import DefaultBaseModel
from tables.models import EmbedderTask
from tables.models.rbac_models.org_scoped import OrgScopedModel


class EmbeddingModel(OrgScopedModel, models.Model):
    name = models.TextField()
    predefined = models.BooleanField(default=False)
    embedding_provider = models.ForeignKey(
        "Provider", on_delete=models.SET_NULL, null=True, default=None
    )
    deployment = models.TextField(null=True, blank=True)
    base_url = models.URLField(null=True, blank=True, default=None)
    is_visible = models.BooleanField(default=True)
    is_custom = models.BooleanField(default=False)
    tags = models.ManyToManyField(
        EmbeddingModelTag, blank=True, related_name="embedding_models"
    )

    class Meta(OrgScopedModel.Meta):
        unique_together = (
            "name",
            "embedding_provider",
        )


class EmbeddingConfig(OrgScopedModel, models.Model):
    model = models.ForeignKey("EmbeddingModel", on_delete=models.SET_NULL, null=True)
    custom_name = models.TextField()
    task_type = models.CharField(
        max_length=255, choices=EmbedderTask.choices, default=EmbedderTask.RETRIEVAL_DOC
    )
    api_key = models.TextField(null=True, blank=True)
    is_visible = models.BooleanField(default=True)
    tags = models.ManyToManyField(
        EmbeddingConfigTag, blank=True, related_name="embedding_configs"
    )

    class Meta(OrgScopedModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["org", "custom_name"],
                name="unique_embeddingconfig_name_per_org",
            ),
        ]

    def delete(self, *args, **kwargs):
        from tables.models import set_field_value_null_in_tool_configs
        from tables.models import ToolConfigField

        embedding_config_id = self.pk
        super().delete(*args, **kwargs)
        set_field_value_null_in_tool_configs(
            field_type=ToolConfigField.FieldType.EMBEDDING_CONFIG,
            value=embedding_config_id,
        )


class DefaultEmbeddingConfig(DefaultBaseModel):
    model = models.ForeignKey("EmbeddingModel", on_delete=models.SET_NULL, null=True)
    task_type = models.CharField(
        max_length=255, choices=EmbedderTask.choices, default=EmbedderTask.RETRIEVAL_DOC
    )
    api_key = models.TextField(null=True, blank=True)
