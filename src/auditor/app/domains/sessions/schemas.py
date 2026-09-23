"""
Sessions-domain request/response Pydantic models for the search and export
endpoints. Lives here (not in app/controllers/*.py) so those controllers
stay domain-generic - they pull these types off the `AuditDomain` instance
(see app/domains/base.py's `ApiSpec.search_request_model`/
`search_response_model`/`export_request_model` fields, reached via
`AuditDomain.api`) instead of importing sessions-specific classes
directly. A second domain gets its own schemas.py sibling with the same
shape, wired onto its own AuditDomain instance in its own domain.py -
neither controller needs to change.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domains.sessions.docs import (
    FILTERS_FIELD_DESCRIPTION,
    MATCH_SCOPE_FIELD_DESCRIPTION,
    SEARCH_REQUEST_EXAMPLES,
    SESSION_SEARCH_REQUEST_DESCRIPTION,
)
from app.domains.sessions.expansion import MatchScope
from app.filtering.ast import FilterNode
from app.filtering.query_language import parse_query
from app.swagger_schemas import QUERY_FIELD_DESCRIPTION


class SessionSearchRequest(BaseModel):
    __doc__ = SESSION_SEARCH_REQUEST_DESCRIPTION

    filters: dict | None = Field(default=None, description=FILTERS_FIELD_DESCRIPTION)
    query: str | None = Field(default=None, description=QUERY_FIELD_DESCRIPTION)
    match_scope: MatchScope = Field(
        default_factory=MatchScope, description=MATCH_SCOPE_FIELD_DESCRIPTION
    )
    cursor: str | None = Field(default=None)
    size: int = Field(default=50, le=1000)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": list(SEARCH_REQUEST_EXAMPLES.values())},
    )

    @model_validator(mode="after")
    def _filters_xor_query(self):
        if self.filters is not None and self.query is not None:
            raise ValueError(
                "'filters' and 'query' are mutually exclusive - send exactly one"
            )
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
            raise ValueError(
                "'filters' and 'query' are mutually exclusive - send exactly one"
            )
        return self

    def resolve_filter_node(self) -> FilterNode | None:
        if self.filters is not None:
            return self.filters
        if self.query:
            return parse_query(self.query)
        return None
