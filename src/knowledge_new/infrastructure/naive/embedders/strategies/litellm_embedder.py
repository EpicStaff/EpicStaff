import litellm
import settings
from application.ports import AbstractEmbedder
from domain.models import Embedding, EmbeddingConfig
from infrastructure.token_estimation import count_tokens_batch, qualified_model_name


def _endpoint_overrides(config: EmbeddingConfig) -> dict:
    """Endpoint overrides for `config`, applied to every provider when set.

    The embedding config's own `base_url` and `extra_headers` win; the
    deployment-wide settings are the fallback.

    The deployment-wide headers are a credential for the deployment-wide
    endpoint, so they are sent only when the config does not point elsewhere:
    with no config `base_url`, or one equal to the env base URL. Otherwise any
    user who can set a model's `base_url` could send the gateway key to a host
    of their choosing. Where both apply, headers merge with the config's value
    winning on a name both define; HTTP header names are case-insensitive, so
    `ApiKey` in the config replaces `apikey` from the env.

    `api_base` is the OpenAI-style base that litellm appends `/embeddings` to,
    not the full embeddings URL.
    """
    overrides = {}
    api_base = config.base_url or settings.CUSTOM_EMBED_BASE_URL
    if api_base:
        overrides["api_base"] = api_base
    env_headers = {}
    if _targets_env_endpoint(config.base_url):
        config_header_names = {name.lower() for name in config.extra_headers}
        env_headers = {
            name: value
            for name, value in (settings.EMBEDDING_HEADERS or {}).items()
            if name.lower() not in config_header_names
        }
    extra_headers = {**env_headers, **config.extra_headers}
    if extra_headers:
        overrides["extra_headers"] = extra_headers
    return overrides


def _targets_env_endpoint(config_base_url: str | None) -> bool:
    """Whether a config with `config_base_url` calls the deployment-wide endpoint."""
    if not config_base_url:
        return True
    env_base_url = settings.CUSTOM_EMBED_BASE_URL
    return bool(env_base_url) and config_base_url.rstrip("/") == env_base_url.rstrip("/")


class LiteLLMEmbedder(AbstractEmbedder):
    """Embed text through litellm, routing to the provider by `config.provider`."""

    async def _embed(self, text: str) -> Embedding:
        text = text.replace("\n", " ")
        response = await litellm.aembedding(
            input=[text],
            api_key=self.api_key,
            model=self.config.model,
            custom_llm_provider=self.config.provider,
            **_endpoint_overrides(self.config),
            **self._extra_params(),
        )
        result = response.data
        vector = result[0]["embedding"] if result else []
        return Embedding(vector=vector, tokens=await self._billed_tokens(response, text))

    async def _billed_tokens(self, response, text: str) -> int:
        """Return the prompt tokens the provider reported for `response`.

        Some providers return no usage; the count is then litellm's local tokenizer
        estimate for `text`, which is close but not what the provider billed. It runs
        off the event loop.
        """
        usage = getattr(response, "usage", None)
        reported = getattr(usage, "prompt_tokens", None)
        if reported:
            return reported
        model = qualified_model_name(self.config.provider, self.config.model)
        (counted,) = await count_tokens_batch(model, [text])
        return counted

    def _extra_params(self) -> dict:
        """Provider-specific params merged into the litellm call."""
        return {}


class CohereLiteLLMEmbedder(LiteLLMEmbedder):
    def _extra_params(self) -> dict:
        # Cohere v3 defaults to `search_document`; keep the pre-litellm behaviour.
        return {"input_type": "search_query"}
