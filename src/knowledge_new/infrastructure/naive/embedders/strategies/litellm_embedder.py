import litellm
import settings
from application.ports import AbstractEmbedder


def _endpoint_overrides() -> dict:
    """Deployment-wide endpoint overrides, applied to every provider when set.

    `api_base` is the OpenAI-style base that litellm appends `/embeddings` to,
    not the full embeddings URL.
    """
    overrides = {}
    if settings.CUSTOM_EMBED_BASE_URL:
        overrides["api_base"] = settings.CUSTOM_EMBED_BASE_URL
    if settings.EMBEDDING_HEADERS:
        overrides["extra_headers"] = settings.EMBEDDING_HEADERS
    return overrides


class LiteLLMEmbedder(AbstractEmbedder):
    """Embed text through litellm, routing to the provider by `config.provider`."""

    async def _embed(self, text: str) -> list[float]:
        text = text.replace("\n", " ")
        response = await litellm.aembedding(
            input=[text],
            api_key=self.api_key,
            model=self.config.model,
            custom_llm_provider=self.config.provider,
            **_endpoint_overrides(),
            **self._extra_params(),
        )
        result = response.data
        if result:
            return result[0]["embedding"]
        return []

    def _extra_params(self) -> dict:
        """Provider-specific params merged into the litellm call."""
        return {}


class CohereLiteLLMEmbedder(LiteLLMEmbedder):
    def _extra_params(self) -> dict:
        # Cohere v3 defaults to `search_document`; keep the pre-litellm behaviour.
        return {"input_type": "search_query"}
