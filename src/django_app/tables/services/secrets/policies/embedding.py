from tables.models.embedding_models import EmbeddingConfig
from tables.services.secrets.policies.base import RowWrite, SecretPolicy, model_destination

#: EmbeddingModel fields that never affect where a request goes; see
#: LLM_MODEL_NON_ROUTING_FIELDS for why the list names what does NOT route.
EMBEDDING_MODEL_NON_ROUTING_FIELDS = frozenset({"is_visible", "tags"})


class EmbeddingConfigSecretPolicy(SecretPolicy):
    reference_fields = ("api_key_secret_id",)
    approval_model = EmbeddingConfig
    approval_label = "Embedding config"

    def destination(self, write: RowWrite) -> dict:
        """The model's identity (see `model_destination`): its fields route the API key."""
        return {"model": model_destination(write.value_after_save("model"))}

    def carries_secret(self, write: RowWrite) -> bool:
        api_key_secret = write.value_after_save(
            "api_key_secret", persisted_attribute="api_key_secret_id"
        )
        return api_key_secret is not None


class EmbeddingModelSecretPolicy(SecretPolicy):
    def destination(self, write: RowWrite) -> dict:
        """Every writable field except the cosmetic ones: today name, embedding_provider,
        deployment and base_url. The converter and the knowledge service route on the
        first three plus the provider; `deployment` is read by nothing yet but is an
        Azure routing field by meaning, so it stays gated."""
        return write.writable_values_after_save(exclude=EMBEDDING_MODEL_NON_ROUTING_FIELDS)

    def carries_secret(self, write: RowWrite) -> bool:
        """Whether any config using this model sends its API key to where it routes.

        Not scoped to the active org, for the same reason as LLMModelSecretPolicy.
        """
        return EmbeddingConfig.objects.filter(
            model=write.instance, api_key_secret__isnull=False
        ).exists()


EMBEDDING_CONFIG_SECRET_POLICY = EmbeddingConfigSecretPolicy()
EMBEDDING_MODEL_SECRET_POLICY = EmbeddingModelSecretPolicy()
