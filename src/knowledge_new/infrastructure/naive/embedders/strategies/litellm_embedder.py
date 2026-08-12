import litellm
from application.ports import AbstractEmbedder


class LiteLLMEmbedder(AbstractEmbedder):
    """Embed text through litellm, routing to the provider by `config.provider`."""

    async def _embed(self, text: str) -> list[float]:
        text = text.replace("\n", " ")
        response = await litellm.aembedding(
            model=self.config.model,
            input=[text],
            api_key=self.config.api_key,
            custom_llm_provider=self.config.provider,
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
