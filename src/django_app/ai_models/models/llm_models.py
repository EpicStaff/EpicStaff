from django.core.validators import MinValueValidator
from django.db import models
from rbac.models.last_edit import LastEditTrackedModel
from rbac.models.org_scoped import OrgScopedModel
from tables.validators.finite_number_validator import validate_finite_number

from ai_models.models.provider import Provider
from ai_models.models.tag_models import LLMConfigTag, LLMModelTag


class LLMModel(OrgScopedModel, models.Model):
    name = models.TextField()
    predefined = models.BooleanField(default=False)
    description = models.TextField(null=True, blank=True)
    llm_provider = models.ForeignKey(Provider, on_delete=models.SET_NULL, null=True)
    is_visible = models.BooleanField(default=True)
    is_custom = models.BooleanField(default=False)
    tags = models.ManyToManyField(LLMModelTag, blank=True, related_name="llm_models")

    class Meta(OrgScopedModel.Meta):
        db_table = "tables_llmmodel"
        constraints = [
            models.UniqueConstraint(
                fields=["org", "name", "llm_provider"],
                name="unique_llmmodel_name_provider_per_org",
            ),
            models.UniqueConstraint(
                fields=["name", "llm_provider"],
                condition=models.Q(org__isnull=True),
                name="unique_llmmodel_name_provider_builtin",
            ),
        ]

    def __str__(self):
        return self.name


class LLMConfig(OrgScopedModel, LastEditTrackedModel):
    custom_name = models.TextField()
    # RESTRICT, not PROTECT: a model row in use is never deleted on its own, but deleting the
    # organization still removes its custom models together with the configs that use them.
    model = models.ForeignKey(LLMModel, on_delete=models.RESTRICT, null=True)
    # The model's settings (temperature, max_tokens…) and the provider's connection fields
    # (endpoint, region…); the model catalog says which keys each may hold.
    parameters = models.JSONField(default=dict, db_default={}, blank=True)
    connection = models.JSONField(default=dict, db_default={}, blank=True)
    context_window = models.IntegerField(
        default=16000,
        validators=[MinValueValidator(1000)],
    )
    api_key_secret = models.ForeignKey(
        "tables.Secret",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="llm_configs",
    )
    extra_headers = models.JSONField(default=dict, blank=True)
    timeout = models.FloatField(default=120.0, null=True, blank=True)
    input_cost_per_token = models.FloatField(
        null=True,
        blank=True,
        validators=[validate_finite_number, MinValueValidator(0.0)],
        help_text="USD per prompt token. Null uses litellm's price map. Set together with output_cost_per_token.",
    )
    output_cost_per_token = models.FloatField(
        null=True,
        blank=True,
        validators=[validate_finite_number, MinValueValidator(0.0)],
        help_text="USD per completion token. Null uses litellm's price map. Set together with input_cost_per_token.",
    )
    is_visible = models.BooleanField(default=True)
    tags = models.ManyToManyField(LLMConfigTag, blank=True, related_name="llm_configs")
    # Nullable because configs created before this column existed have no known
    # creation time; they stay NULL rather than getting a guessed one.
    created_at = models.DateTimeField(auto_now_add=True, null=True)

    class Meta(OrgScopedModel.Meta):
        db_table = "tables_llmconfig"
        constraints = [
            models.UniqueConstraint(
                fields=["org", "custom_name"],
                name="unique_llmconfig_name_per_org",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(input_cost_per_token__isnull=True, output_cost_per_token__isnull=True)
                    | models.Q(
                        input_cost_per_token__isnull=False, output_cost_per_token__isnull=False
                    )
                ),
                name="llmconfig_token_prices_set_together",
            ),
        ]
