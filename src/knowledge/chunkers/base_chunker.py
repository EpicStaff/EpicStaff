from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class BaseChunkData:
    """Base dataclass for chunk data returned by chunkers."""

    text: str
    token_count: Optional[int] = None
    overlap_start_index: Optional[int] = None
    overlap_end_index: Optional[int] = None


class BaseChunker(ABC):
    @abstractmethod
    def chunk(self, text: str) -> list[BaseChunkData]:
        pass
