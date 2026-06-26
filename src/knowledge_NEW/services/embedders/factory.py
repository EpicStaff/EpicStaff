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
    """Create the embedder registered for `provider`.

    Args:
        provider: Embedding provider selecting the embedder implementation.
        config: Configuration passed to the embedder.

    Raises:
        UnsupportedError: If `provider` has no registered embedder.
    """
    if provider not in _STRATEGIES:
        raise UnsupportedError("embedding provider", provider)
    return _STRATEGIES[provider](config)
