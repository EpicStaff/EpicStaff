import litellm
import settings
from application.ports import AbstractEmbedder
from domain.models import Embedding, EmbeddingConfig
from infrastructure.database.mappers.embedding_arguments import embedding_call_arguments
from infrastructure.token_estimation import count_tokens_batch, qualified_model_name
from src.shared.models.ai_providers import EmbedderConfigData


def _connection_arguments(config: EmbeddingConfig, api_key: str) -> dict:
    """The key, connection arguments and headers for `config`, applied to every provider.

    The embedding config's own `api_base` and `extra_headers` win; the deployment-wide
    `CUSTOM_EMBED_BASE_URL` is the fallback base URL.

    `api_base` is the OpenAI-style base that litellm appends `/embeddings` to,
    not the full embeddings URL. Holds secrets: never log it.
    """
    arguments = EmbedderConfigData(
        model=config.model, connection=config.connection, api_key=api_key
    ).connection_kwargs()
    if "api_base" not in arguments and settings.CUSTOM_EMBED_BASE_URL:
        arguments["api_base"] = settings.CUSTOM_EMBED_BASE_URL
    if config.extra_headers:
        arguments["extra_headers"] = config.extra_headers
    return arguments


class LiteLLMEmbedder(AbstractEmbedder):
    """Embed text through litellm, routing to the provider by `config.provider`."""

    async def _embed(self, text: str) -> Embedding:
        text = text.replace("\n", " ")
        response = await litellm.aembedding(
            input=[text],
            model=self.config.model,
            custom_llm_provider=self.config.provider,
            **{
                **embedding_call_arguments(self.config.parameters),
                **_connection_arguments(self.config, self.api_key),
                **self._extra_params(),
            },
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
