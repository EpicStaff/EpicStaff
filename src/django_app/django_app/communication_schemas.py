from typing import Literal, Optional

from pydantic import BaseModel


class IndexRequest(BaseModel):
    rag_id: int
    rag_strategy: Literal["naive", "graph"]


class CancelRequest(BaseModel):
    target_request: dict


class PrechunkRequest(BaseModel):
    rag_id: int
    rag_strategy: Literal["naive", "graph"]
    document_id: int


class PreviewChunk(BaseModel):
    text: str
    token_count: Optional[int] = None
    overlap_start: Optional[int] = None
    overlap_end: Optional[int] = None


class PrechunkResponse(BaseModel):
    request: PrechunkRequest
    chunks: list[PreviewChunk]
