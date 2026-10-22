import pytest
from domain.enums import ChunkStrategyEnum
from domain.models import ChunkingConfig
from infrastructure.naive.chunkers.strategies.token_chunker import load_gpt2_tokenizer


def make_config(
    strategy: ChunkStrategyEnum,
    chunk_size: int = 100,
    chunk_overlap: int = 0,
    extra: dict | None = None,
) -> ChunkingConfig:
    return ChunkingConfig(
        chunk_strategy=strategy,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        extra=extra or {},
    )


@pytest.fixture(autouse=True)
def fresh_gpt2_tokenizer():
    """The tokenizer is cached per process; tests that change TOKENIZER_PATH need a cold cache."""
    load_gpt2_tokenizer.cache_clear()
    yield
    load_gpt2_tokenizer.cache_clear()
