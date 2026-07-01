from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class NaiveSearchConfig(BaseModel):
    rag_strategy: Literal["naive"] = "naive"
    search_limit: int = 3
    similarity_threshold: float = 0.2


class GraphSearchConfig(BaseModel):
    rag_strategy: Literal["graph"] = "graph"
    method: Literal["basic", "local", "global", "drift"] = "basic"
    prompt: str = ""
    k: int = 10
    max_context_tokens: int = 12000


RagSearchConfig = Annotated[
    Union[GraphSearchConfig, NaiveSearchConfig],
    Field(discriminator="rag_strategy"),
]


class SearchRequest(BaseModel):
    rag_id: int
    query: str
    search_config: RagSearchConfig


class FoundChunk(BaseModel):
    order: int
    similarity: float
    text: str
    source: str = ""


class SearchResponse(BaseModel):
    request: SearchRequest
    chunks: list[FoundChunk]
