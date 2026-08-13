from domain.models import ChunkingConfig, FoundChunk, PreviewChunk, SearchConfig
from presentation.rest.schemas.base import BaseSchema


class IndexInputSchema(BaseSchema):
    document_ids: frozenset[int]


class PrechunkInputSchema(BaseSchema):
    document_id: int
    chunking_config: ChunkingConfig


class PrechunkOutputSchema(BaseSchema):
    chunks: list[PreviewChunk]


class SearchInputSchema(BaseSchema):
    query: str
    search_config: SearchConfig


class SearchOutputSchema(BaseSchema):
    result: list[FoundChunk] | str
