from domain.enums import ChunkStrategyEnum
from domain.models import ChunkingConfig


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
