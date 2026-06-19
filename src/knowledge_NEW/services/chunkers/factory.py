from enums import ChunkStrategyEnum
from errors import UnsupportedError
from models import ChunkingConfig
from services.chunkers.base import AbstractChunker
from services.chunkers import strategies


_STRATEGIES: dict[ChunkStrategyEnum, type[AbstractChunker]] = {
    ChunkStrategyEnum.CHARACTER: strategies.CharacterChunker,
    ChunkStrategyEnum.CSV: strategies.CSVChunker,
    ChunkStrategyEnum.HTML: strategies.HTMLChunker,
    ChunkStrategyEnum.JSON: strategies.JSONChunker,
    ChunkStrategyEnum.MARKDOWN: strategies.MarkdownChunker,
    ChunkStrategyEnum.TOKEN: strategies.TokenChunker,
}


def build_chunker(
    strategy: ChunkStrategyEnum, config: ChunkingConfig
) -> AbstractChunker:
    """Instantiate a chunker for the given strategy.

    Args:
        strategy: Chunking strategy to use.
        config: Chunking parameters passed to the chunker.

    Returns:
        A chunker configured for `strategy`.

    Raises:
        UnsupportedError: If `strategy` has no registered implementation.
    """
    if strategy not in _STRATEGIES:
        raise UnsupportedError("chunker strategy", strategy)
    return _STRATEGIES[strategy](config)
