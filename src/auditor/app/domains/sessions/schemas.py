"""Sessions-domain request/response models for the search and export endpoints."""

from typing import Literal

from app.domains.sessions.docs import (
    FILTERS_FIELD_DESCRIPTION,
    MATCH_SCOPE_FIELD_DESCRIPTION,
    SEARCH_REQUEST_EXAMPLES,
    SESSION_SEARCH_REQUEST_DESCRIPTION,
)
from app.domains.sessions.expansion import MatchScope
from app.filtering.ast import FilterNode
from app.filtering.query_language import parse_query
from app.swagger_schemas import (
    CURSOR_FIELD_DESCRIPTION,
    QUERY_FIELD_DESCRIPTION,
    SIZE_FIELD_DESCRIPTION,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator


class SessionSearchRequest(BaseModel):
    __doc__ = SESSION_SEARCH_REQUEST_DESCRIPTION

    filters: dict | None = Field(default=None, description=FILTERS_FIELD_DESCRIPTION)
    query: str | None = Field(default=None, description=QUERY_FIELD_DESCRIPTION)
    match_scope: MatchScope = Field(
        default_factory=MatchScope, description=MATCH_SCOPE_FIELD_DESCRIPTION
    )
    cursor: str | None = Field(default=None, description=CURSOR_FIELD_DESCRIPTION)
    size: int = Field(default=50, ge=1, le=1000, description=SIZE_FIELD_DESCRIPTION)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": list(SEARCH_REQUEST_EXAMPLES.values())},
    )

    @model_validator(mode="after")
    def _filters_xor_query(self):
        if self.filters is not None and self.query is not None:
            raise ValueError("'filters' and 'query' are mutually exclusive - send exactly one")
        return self

    def resolve_filter_node(self) -> FilterNode | None:
        if self.filters is not None:
            return self.filters
        if self.query:
            return parse_query(self.query)
        return None


class SessionSearchResponse(BaseModel):
    items: list[dict]
    next_cursor: str | None
    partial: bool = False


class SessionExportRequest(BaseModel):
    format: Literal["json", "csv"] = "json"
    filters: dict | None = Field(default=None, description=FILTERS_FIELD_DESCRIPTION)
    query: str | None = Field(default=None, description=QUERY_FIELD_DESCRIPTION)
    match_scope: MatchScope = Field(
        default_factory=MatchScope, description=MATCH_SCOPE_FIELD_DESCRIPTION
    )

    @model_validator(mode="after")
    def _filters_xor_query(self):
        if self.filters is not None and self.query is not None:
            raise ValueError("'filters' and 'query' are mutually exclusive - send exactly one")
        return self

    def resolve_filter_node(self) -> FilterNode | None:
        if self.filters is not None:
            return self.filters
        if self.query:
            return parse_query(self.query)
        return None
