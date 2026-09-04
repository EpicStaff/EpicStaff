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
    base_url = models.TextField(null=True, blank=True, default=None)
    is_visible = models.BooleanField(default=True)
    is_custom = models.BooleanField(default=False)
    tags = models.ManyToManyField(
        EmbeddingModelTag, blank=True, related_name="embedding_models"
    )

    class Meta(OrgScopedModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["org", "name", "embedding_provider"],
                name="unique_embeddingmodel_name_provider_per_org",
            ),
            # Postgres treats NULLs as distinct — see LLMModel.
            models.UniqueConstraint(
                fields=["name", "embedding_provider"],
                condition=models.Q(org__isnull=True),
                name="unique_embeddingmodel_name_provider_builtin",
            ),
        ]


class EmbeddingConfig(OrgScopedModel, models.Model):
    model = models.ForeignKey("EmbeddingModel", on_delete=models.SET_NULL, null=True)
    custom_name = models.TextField()
    task_type = models.CharField(
        max_length=255, choices=EmbedderTask.choices, default=EmbedderTask.RETRIEVAL_DOC
    )
    api_key_secret = models.ForeignKey(
        "Secret",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="embedding_configs",
    )
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


class DefaultEmbeddingConfig(DefaultBaseModel):
    model = models.ForeignKey("EmbeddingModel", on_delete=models.SET_NULL, null=True)
    task_type = models.CharField(
        max_length=255, choices=EmbedderTask.choices, default=EmbedderTask.RETRIEVAL_DOC
    )
