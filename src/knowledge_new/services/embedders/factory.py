from enums import EmbedderProviderEnum
from errors import UnsupportedError
from models import EmbeddingConfig
from services.embedders import strategies
from services.embedders.base import AbstractEmbedder

_STRATEGIES: dict[EmbedderProviderEnum, type[AbstractEmbedder]] = {
    EmbedderProviderEnum.COHERE: strategies.CohereLiteLLMEmbedder,
    EmbedderProviderEnum.GEMINI: strategies.LiteLLMEmbedder,
    EmbedderProviderEnum.MISTRAL: strategies.LiteLLMEmbedder,
    EmbedderProviderEnum.OPENAI: strategies.LiteLLMEmbedder,
    EmbedderProviderEnum.TOGETHER_AI: strategies.LiteLLMEmbedder,
}


def build_embedder(
    provider: EmbedderProviderEnum, config: EmbeddingConfig
) -> AbstractEmbedder:
    """Create the embedder registered for `provider`.

    Args:
        provider: Embedding provider selecting the embedder implementation.
        config: Configuration passed to the embedder.

    Raises:
        UnsupportedError: If `provider` has no registered embedder.
    """
    if provider not in _STRATEGIES:
        raise UnsupportedError(that="embedding provider", got=provider)
    return _STRATEGIES[provider](config)
