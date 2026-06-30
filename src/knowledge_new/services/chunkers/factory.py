from enums import ChunkStrategyEnum
from errors import UnsupportedError
from models import ChunkingConfig
from services.chunkers import strategies
from services.chunkers.base import AbstractChunker

_STRATEGIES: dict[ChunkStrategyEnum, type[AbstractChunker]] = {
    ChunkStrategyEnum.CHARACTER: strategies.CharacterChunker,
    ChunkStrategyEnum.CSV: strategies.CSVChunker,
    ChunkStrategyEnum.HTML: strategies.HTMLChunker,
    ChunkStrategyEnum.JSON: strategies.JSONChunker,
    ChunkStrategyEnum.MARKDOWN: strategies.MarkdownChunker,
    ChunkStrategyEnum.TOKEN: strategies.TokenChunker,
}


def build_chunker(strategy: ChunkStrategyEnum, config: ChunkingConfig) -> AbstractChunker:
    """Create the chunker registered for `strategy`.

    Args:
        strategy: Chunking strategy selecting the chunker implementation.
        config: Configuration passed to the chunker.

    Raises:
        UnsupportedError: If `strategy` has no registered chunker.
    """
    if strategy not in _STRATEGIES:
        raise UnsupportedError(that="chunker strategy", got=strategy)
    return _STRATEGIES[strategy](config)
