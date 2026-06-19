from enums import EmbedderProviderEnum
from errors import UnsupportedError
from models import EmbeddingConfig
from services.embedders.base import AbstractEmbedder
from services.embedders import strategies


_STRATEGIES: dict[EmbedderProviderEnum, type[AbstractEmbedder]] = {
    EmbedderProviderEnum.COHERE: strategies.CohereEmbedder,
    EmbedderProviderEnum.GEMINI: strategies.GeminiEmbedder,
    EmbedderProviderEnum.MISTRAL: strategies.MistralEmbedder,
    EmbedderProviderEnum.OPENAI: strategies.OpenAIEmbedder,
    EmbedderProviderEnum.TOGETHER_AI: strategies.TogetherAIEmbedder,
}


def build_embedder(
    provider: EmbedderProviderEnum, config: EmbeddingConfig
) -> AbstractEmbedder:
    """Build the embedder registered for `provider`.

    Args:
        provider: Embedding provider to build a strategy for.
        config: Configuration passed to the selected embedder.

    Returns:
        An embedder instance for `provider`.

    Raises:
        UnsupportedError: If no strategy is registered for `provider`.
    """
    if provider not in _STRATEGIES:
        raise UnsupportedError("embedding provider", provider)
    return _STRATEGIES[provider](config)
