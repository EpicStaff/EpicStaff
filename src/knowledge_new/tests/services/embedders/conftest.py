from domain.enums import EmbedderProviderEnum
from domain.models import EmbeddingConfig


def make_config(provider: EmbedderProviderEnum) -> EmbeddingConfig:
    """Build a minimal EmbeddingConfig for the given provider."""
    return EmbeddingConfig(provider=provider, api_key="k", model="m")
