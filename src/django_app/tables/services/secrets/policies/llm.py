from tables.models.llm_models import LLMConfig
from tables.services.secrets.policies.base import RowWrite, SecretPolicy, model_destination
from tables.services.secrets.secret_resolver import secret_names_in_headers

#: LLMModel fields that never affect where a request goes. Every other writable field
#: is part of the model's destination, so a field added later is gated by default.
LLM_MODEL_NON_ROUTING_FIELDS = frozenset({"description", "is_visible", "capabilities", "tags"})


class LLMConfigSecretPolicy(SecretPolicy):
    reference_fields = ("api_key_secret_id",)
    header_fields = ("extra_headers",)
    approval_model = LLMConfig
    approval_label = "LLM config"

    def destination(self, write: RowWrite) -> dict:
        """The model's identity (see `model_destination`) and the config's own base_url.

        `LLMConfig.base_url` is read by nothing today, but it is writable and is the
        obvious field to wire up next, so a change to it is gated too rather than left
        as a latent bypass.
        """
        return {
            "model": model_destination(write.value_after_save("model")),
            "base_url": write.value_after_save("base_url"),
        }

    def carries_secret(self, write: RowWrite) -> bool:
        api_key_secret = write.value_after_save(
            "api_key_secret", persisted_attribute="api_key_secret_id"
        )
        return api_key_secret is not None or bool(
            secret_names_in_headers(write.value_after_save("extra_headers"))
        )


class LLMModelSecretPolicy(SecretPolicy):
    def destination(self, write: RowWrite) -> dict:
        """Every writable field except the cosmetic ones: today name, llm_provider,
        deployment_id, api_version and base_url, all of which the converter sends on."""
        return write.writable_values_after_save(exclude=LLM_MODEL_NON_ROUTING_FIELDS)

    def carries_secret(self, write: RowWrite) -> bool:
        """Whether any config using this model sends a secret to where it routes.

        Not scoped to the active org: a custom model is visible to its own org only, and
        counting every referencing config can only deny more, never leak.
        """
        dependents = LLMConfig.objects.filter(model=write.instance)
        if dependents.filter(api_key_secret__isnull=False).exists():
            return True
        return any(
            secret_names_in_headers(extra_headers)
            for extra_headers in dependents.values_list("extra_headers", flat=True)
        )


LLM_CONFIG_SECRET_POLICY = LLMConfigSecretPolicy()
LLM_MODEL_SECRET_POLICY = LLMModelSecretPolicy()
REALTIME_CONFIG_SECRET_POLICY = SecretPolicy(reference_fields=("api_key_secret_id",))
REALTIME_TRANSCRIPTION_CONFIG_SECRET_POLICY = SecretPolicy(reference_fields=("api_key_secret_id",))
