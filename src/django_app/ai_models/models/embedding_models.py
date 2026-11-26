from django.db import models
from rbac.models.last_edit import LastEditTrackedModel
from rbac.models.org_scoped import OrgScopedModel

from ai_models.models.tag_models import EmbeddingConfigTag, EmbeddingModelTag


class EmbeddingModel(OrgScopedModel, models.Model):
    name = models.TextField()
    predefined = models.BooleanField(default=False)
    embedding_provider = models.ForeignKey(
        "Provider", on_delete=models.SET_NULL, null=True, default=None
    )
    is_visible = models.BooleanField(default=True)
    is_custom = models.BooleanField(default=False)
    tags = models.ManyToManyField(EmbeddingModelTag, blank=True, related_name="embedding_models")

    class Meta(OrgScopedModel.Meta):
        db_table = "tables_embeddingmodel"
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


class EmbeddingConfig(OrgScopedModel, LastEditTrackedModel, models.Model):
    # RESTRICT, not PROTECT: a model row in use is never deleted on its own, but deleting the
    # organization still removes its custom models together with the configs that use them.
    model = models.ForeignKey("EmbeddingModel", on_delete=models.RESTRICT, null=True)
    custom_name = models.TextField()
    # The model's settings (task_type, dimensions…) and the provider's connection fields;
    # the model catalog says which keys each may hold.
    parameters = models.JSONField(default=dict, db_default={}, blank=True)
    connection = models.JSONField(default=dict, db_default={}, blank=True)
    api_key_secret = models.ForeignKey(
        "tables.Secret",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="embedding_configs",
    )
    # db_default lets a writer that predates this column (an old pod mid-deploy, a
    # historical migration model) still insert rows; default fills it in the ORM.
    extra_headers = models.JSONField(default=dict, db_default={}, blank=True)
    is_visible = models.BooleanField(default=True)
    tags = models.ManyToManyField(EmbeddingConfigTag, blank=True, related_name="embedding_configs")
    # Nullable because configs created before this column existed have no known
    # creation time; they stay NULL rather than getting a guessed one.
    created_at = models.DateTimeField(auto_now_add=True, null=True)

    class Meta(OrgScopedModel.Meta):
        db_table = "tables_embeddingconfig"
        constraints = [
            models.UniqueConstraint(
                fields=["org", "custom_name"],
                name="unique_embeddingconfig_name_per_org",
            ),
        ]
