from fastapi import APIRouter, Body, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.security import require_audit_action
from app.filtering.ast import FilterNode, validate_filter_node
from app.filtering.query_language import parse_query
from app.repositories.opensearch_query_compiler import compile as compile_filters
from app.services.duration_filter import apply_duration_filter, split_duration_filter
from app.services.match_scope import MatchScope, expand_and_mark
from app.swagger_schemas import (
    CURSOR_FIELD_DESCRIPTION,
    FILTERS_FIELD_DESCRIPTION,
    MATCH_SCOPE_FIELD_DESCRIPTION,
    QUERY_FIELD_DESCRIPTION,
    SEARCH_REQUEST_EXAMPLES,
    SEARCH_SESSIONS_DESCRIPTION,
    SESSION_SEARCH_REQUEST_DESCRIPTION,
    SIZE_FIELD_DESCRIPTION,
)

router = APIRouter(tags=["Browse"])


class SessionSearchRequest(BaseModel):
    __doc__ = SESSION_SEARCH_REQUEST_DESCRIPTION

    filters: dict | None = Field(default=None, description=FILTERS_FIELD_DESCRIPTION)
    query: str | None = Field(default=None, description=QUERY_FIELD_DESCRIPTION)
    match_scope: MatchScope = Field(
        default_factory=MatchScope, description=MATCH_SCOPE_FIELD_DESCRIPTION
    )
    cursor: str | None = Field(default=None, description=CURSOR_FIELD_DESCRIPTION)
    size: int = Field(default=50, le=1000, description=SIZE_FIELD_DESCRIPTION)

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


async def _run_search(
    request: Request, body: SessionSearchRequest, claims: dict
) -> SessionSearchResponse:
    repository = request.app.state.session_audit_repository

    org_id = claims["org_id"]
    retention_days = claims["retention_days"]

    filter_node = body.resolve_filter_node()
    if filter_node is not None:
        validate_filter_node(filter_node)

    remainder_node, duration_cond = split_duration_filter(filter_node)

    compiled = compile_filters(
        remainder_node,
        org_id=org_id,
        retention_days=retention_days
    )

    if duration_cond is None:
        events, next_cursor = await repository.query(
            compiled, cursor=body.cursor, size=body.size
        )
        partial = False
    else:
        events, next_cursor, partial = await apply_duration_filter(
            repository,
            compiled,
            duration_cond,
            org_id=org_id,
            retention_days=retention_days,
            size=body.size,
            cursor=body.cursor,
        )

    events = await expand_and_mark(
        repository,
        events,
        body.match_scope,
        org_id=org_id,
        retention_days=retention_days,
    )

    return SessionSearchResponse(
        items=[e.model_dump(mode="json") for e in events],
        next_cursor=next_cursor,
        partial=partial,
    )


@router.post("/api/audit/sessions/search", description=SEARCH_SESSIONS_DESCRIPTION)
async def search_sessions(
    request: Request,
    body: SessionSearchRequest = Body(openapi_examples=SEARCH_REQUEST_EXAMPLES),
    claims: dict = Depends(require_audit_action("read")),
) -> SessionSearchResponse:
    return await _run_search(request, body, claims)
