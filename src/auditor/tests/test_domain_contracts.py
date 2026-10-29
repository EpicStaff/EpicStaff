from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, Field

from app.controllers.query_routes import build_search_router
from app.domains.base import (
    ApiSpec,
    AuditDomain,
    BaseScopeArgs,
    DictFieldCatalog,
    FreeTextFields,
    IndexSpec,
    NullExpander,
    ScopedQueryBuilder,
    ScopingPolicy,
)
from app.domains.sessions.domain import SESSIONS
from app.domains.sessions.expansion import MatchScope, SessionTreeExpander, expand_matches
from app.filtering.ast import FieldSpec, FilterValidationError
from app.filtering.constants import SELECT_OPS, TEXT_CONDITION_OPS
from app.repositories.compiler import FilterCompileError, QueryCompiler
from app.services.matching import expand_and_mark
from app.services.search_pipeline import SearchPipeline
from src.shared.models import BaseAuditEvent, SessionAuditEvent
from tests._auth import auth
from tests._fakes import InMemoryFakeRepository

ORG_ID = 7
NOW = datetime.now(timezone.utc)


class TermsOrgScopingPolicy(ScopingPolicy):
    """Semantically identical org scope, but in a shape the default policy
    never produces - so a query carrying it provably came from this policy."""

    @staticmethod
    def _get_org_scope(org_id: int) -> dict:
        return {"terms": {"org_id": [org_id]}}


class RecordingRepository(InMemoryFakeRepository):
    def __init__(self, events):
        super().__init__(events)
        self.queries: list[dict] = []

    async def query(self, query: dict, cursor: str | None = None, size: int = 50):
        self.queries.append(query)
        return await super().query(query, cursor=cursor, size=size)


def _session_tree() -> list[SessionAuditEvent]:
    return [
        SessionAuditEvent(
            id="sess-1", session_id=100, kind="session", event_time=NOW, org_id=ORG_ID
        ),
        SessionAuditEvent(
            id="node-1",
            parent_id="sess-1",
            session_id=100,
            kind="node",
            event_time=NOW + timedelta(seconds=1),
            org_id=ORG_ID,
        ),
        SessionAuditEvent(
            id="evt-start",
            parent_id="node-1",
            session_id=100,
            kind="event",
            details={"message_type": "start"},
            event_time=NOW + timedelta(seconds=2),
            org_id=ORG_ID,
        ),
        SessionAuditEvent(
            id="evt-finish",
            parent_id="node-1",
            session_id=100,
            kind="event",
            details={"message_type": "finish"},
            event_time=NOW + timedelta(seconds=5),
            org_id=ORG_ID,
        ),
    ]


def _assert_every_query_used_custom_policy(queries: list[dict]) -> None:
    assert queries
    for query in queries:
        clauses = query["bool"]["filter"]
        assert {"terms": {"org_id": [ORG_ID]}} in clauses
        assert {"term": {"org_id": ORG_ID}} not in clauses


# --- ScopingPolicy -----------------------------------------------------


@pytest.mark.asyncio
async def test_expansion_follow_up_queries_use_the_domain_scoping_policy():
    domain = replace(SESSIONS, scoping=TermsOrgScopingPolicy())
    repository = RecordingRepository(_session_tree())

    events, _, _ = await SearchPipeline.from_domain(domain).search(
        repository,
        {"field": "id", "op": "equals", "value": "evt-start"},
        MatchScope(full_session_history=True, ancestors=False),
        org_id=ORG_ID,
        retention_days=0,
        cursor=None,
        size=50,
    )

    assert {event.id for event in events} == {"sess-1", "node-1", "evt-start", "evt-finish"}
    _assert_every_query_used_custom_policy(repository.queries)


@pytest.mark.asyncio
async def test_computed_field_resolution_uses_the_domain_scoping_policy():
    domain = replace(SESSIONS, scoping=TermsOrgScopingPolicy())
    repository = RecordingRepository(_session_tree())

    events, _, _ = await SearchPipeline.from_domain(domain).search(
        repository,
        {
            "op": "and",
            "children": [
                {"field": "kind", "op": "equals", "value": "node"},
                {"field": "duration", "op": "gte", "value": 3},
            ],
        },
        MatchScope(),
        org_id=ORG_ID,
        retention_days=0,
        cursor=None,
        size=50,
    )

    assert [event.id for event in events] == ["node-1"]
    _assert_every_query_used_custom_policy(repository.queries)


@pytest.mark.asyncio
async def test_expansion_never_crosses_org_boundary():
    other_org_event = SessionAuditEvent(
        id="evt-other-org",
        parent_id="node-1",
        session_id=100,
        kind="event",
        event_time=NOW,
        org_id=999,
    )
    repository = InMemoryFakeRepository(_session_tree() + [other_org_event])

    events, _, _ = await SearchPipeline.from_domain(SESSIONS).search(
        repository,
        {"field": "id", "op": "equals", "value": "node-1"},
        MatchScope(children=True),
        org_id=ORG_ID,
        retention_days=0,
        cursor=None,
        size=50,
    )

    assert "evt-other-org" not in {event.id for event in events}


# --- match_scope contract ----------------------------------------------


# --- a flat domain with no match-scope or computed-field concept -------


class FlatAuditEvent(BaseAuditEvent):
    action: str = ""


FLAT_FIELDS = DictFieldCatalog(
    known_fields={"action": FieldSpec(SELECT_OPS), "__text__": FieldSpec(frozenset({"contains"}))},
    free_text=FreeTextFields(fields=("action",)),
)


class FlatSearchRequest(BaseModel):
    filters: dict | None = None
    cursor: str | None = None
    size: int = Field(default=50, ge=1, le=1000)

    def resolve_filter_node(self):
        return self.filters


class FlatSearchResponse(BaseModel):
    items: list[dict]
    next_cursor: str | None
    partial: bool = False


FLAT_DOMAIN: AuditDomain[FlatAuditEvent] = AuditDomain(
    name="flat",
    event_model=FlatAuditEvent,
    index=IndexSpec(
        name="flat_events",
        mapping_path=Path("unused.json"),
        sort_keys=(),
        ism_policy_prefix="flat-retention",
    ),
    fields=FLAT_FIELDS,
    scoping=ScopingPolicy(),
    computed=(),
    expander=NullExpander(),
    resource="FLAT",
    api=ApiSpec(
        search_request_model=FlatSearchRequest,
        search_response_model=FlatSearchResponse,
        export_request_model=FlatSearchRequest,
        search_description="",
        search_examples={},
    ),
)


@pytest.mark.asyncio
async def test_flat_domain_without_match_scope_searches_successfully():
    events = [
        FlatAuditEvent(id="flat-1", org_id=ORG_ID, event_time=NOW, action="login"),
        FlatAuditEvent(id="flat-2", org_id=ORG_ID, event_time=NOW, action="logout"),
        FlatAuditEvent(id="flat-other-org", org_id=999, event_time=NOW, action="login"),
    ]
    app = FastAPI()
    app.include_router(build_search_router(FLAT_DOMAIN))
    app.state.repositories = {FLAT_DOMAIN.name: InMemoryFakeRepository(events)}
    transport = ASGITransport(app=app)
    headers = auth(AUDIT=None, FLAT=["read"])
    async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as client:
        resp = await client.post(
            "/api/audit/flat/search",
            json={"filters": {"field": "action", "op": "equals", "value": "login"}},
        )

    assert resp.status_code == 200
    assert [item["id"] for item in resp.json()["items"]] == ["flat-1"]


@pytest.mark.asyncio
async def test_audit_grant_does_not_open_another_domains_routes():
    app = FastAPI()
    app.include_router(build_search_router(FLAT_DOMAIN))
    app.state.repositories = {FLAT_DOMAIN.name: InMemoryFakeRepository([])}
    transport = ASGITransport(app=app)
    headers = auth(AUDIT=["read", "export"])
    async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as client:
        resp = await client.post("/api/audit/flat/search", json={})

    assert resp.status_code == 403


# --- AuditDomain computed-field consistency ----------------------------


def test_audit_domain_rejects_catalog_computed_field_without_implementation():
    with pytest.raises(ValueError, match="duration"):
        replace(SESSIONS, computed=())


def test_audit_domain_rejects_implementation_not_marked_computed_in_catalog():
    with pytest.raises(ValueError, match="duration"):
        replace(FLAT_DOMAIN, computed=SESSIONS.computed)


# --- DictFieldCatalog --------------------------------------------------


def test_dict_field_catalog_lookups_are_case_insensitive():
    catalog = DictFieldCatalog(
        known_fields={"name": FieldSpec(TEXT_CONDITION_OPS)},
        aliases={"tool": "details.tool"},
        flat_roots=frozenset({"details"}),
        wildcard_subfields={"error": "error.raw"},
    )

    assert catalog.field_spec("NAME") == FieldSpec(TEXT_CONDITION_OPS)
    assert catalog.resolve_alias("Tool") == "details.tool"
    assert catalog.resolve_alias("unaliased") == "unaliased"
    assert catalog.is_flattened_path("Details.Key")
    assert catalog.field_spec("details.anything") is not None
    assert catalog.field_spec("unknown") is None
    assert catalog.wildcard_subfield("ERROR") == "error.raw"
    assert catalog.wildcard_subfield("name") is None
    assert catalog.computed_field_names() == frozenset()


# --- QueryCompiler is driven by the catalog, not hardcoded fields ------


def _compile(catalog, node) -> list[dict]:
    compiled = QueryCompiler(catalog, ScopingPolicy()).compile(node, org_id=1, retention_days=0)
    return compiled["bool"]["filter"]


def test_compiler_free_text_uses_the_catalogs_fields():
    (free_text_clause, _org_scope) = _compile(
        FLAT_FIELDS, {"field": "__text__", "op": "contains", "value": "log"}
    )

    assert free_text_clause == {
        "bool": {
            "should": [{"wildcard": {"action": {"value": "*log*", "case_insensitive": True}}}],
            "minimum_should_match": 1,
        }
    }


def test_compiler_rejects_free_text_for_a_catalog_without_free_text_fields():
    catalog = DictFieldCatalog(known_fields={"__text__": FieldSpec(frozenset({"contains"}))})

    with pytest.raises(FilterCompileError):
        _compile(catalog, {"field": "__text__", "op": "contains", "value": "x"})


def test_compiler_routes_pattern_ops_to_the_catalogs_wildcard_subfield():
    catalog = DictFieldCatalog(
        known_fields={"message": FieldSpec(TEXT_CONDITION_OPS)},
        wildcard_subfields={"message": "message.keyword"},
    )

    (contains_clause, _) = _compile(
        catalog, {"field": "message", "op": "contains", "value": "boom"}
    )
    (empty_clause, _) = _compile(catalog, {"field": "message", "op": "is_empty"})

    assert contains_clause == {
        "wildcard": {"message.keyword": {"value": "*boom*", "case_insensitive": True}}
    }
    assert empty_clause == {"bool": {"must_not": [{"exists": {"field": "message"}}]}}


def test_compiler_rejects_non_numeric_value_for_flattened_range_op():
    with pytest.raises(FilterCompileError):
        _compile(
            SESSIONS.fields, {"field": "details.tokens", "op": "gt", "value": "not-a-number"}
        )


def test_duration_rejects_non_numeric_value_as_validation_error():
    (duration_field,) = SESSIONS.computed

    with pytest.raises(FilterValidationError):
        duration_field.combine([{"field": "duration", "op": "gt", "value": "soon"}])


# --- shared event model ------------------------------------------------


# --- match_scope expansion ---------------------------------------------


@pytest.mark.asyncio
async def test_ancestors_cover_rows_pulled_in_by_rows_before():
    def event(event_id, kind, seconds, parent_id=""):
        return SessionAuditEvent(
            id=event_id, parent_id=parent_id, session_id=100, kind=kind,
            event_time=NOW + timedelta(seconds=seconds), org_id=ORG_ID,
        )

    events = [
        event("sess", "session", 0),
        event("node-a", "node", 1, "sess"),
        event("evt-a1", "event", 2, "node-a"),
        event("node-b", "node", 3, "sess"),
        event("evt-b1", "event", 4, "node-b"),
        event("evt-b2", "event", 5, "node-b"),
    ]
    query_builder = ScopedQueryBuilder(ScopingPolicy(), BaseScopeArgs(ORG_ID, 0))

    result = await expand_matches(
        InMemoryFakeRepository(events),
        [events[4]],
        MatchScope(ancestors=True, rows_before=2),
        query_builder,
    )

    result_ids = [row.id for row in result]
    # evt-a1 arrives via rows_before; without node-a the tree shows it as a detached root.
    assert set(result_ids) == {"sess", "node-a", "evt-a1", "node-b", "evt-b1"}
    assert len(result_ids) == len(set(result_ids))


def _session_event(event_id, parent_id, message_type, status, seconds):
    return SessionAuditEvent(
        id=event_id,
        parent_id=parent_id,
        session_id=100,
        kind="event",
        status=status,
        details={"message_type": message_type},
        event_time=NOW + timedelta(seconds=seconds),
        org_id=ORG_ID,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("session_end_status", ["completed", "failed"])
async def test_session_row_status_comes_from_its_session_end_event(session_end_status):
    session_end = _session_event("evt-end", "sess-1", "session_end", session_end_status, 9)
    repository = RecordingRepository(_session_tree() + [session_end])
    matched = [event for event in _session_tree() if event.id == "evt-finish"]
    query_builder = ScopedQueryBuilder(ScopingPolicy(), BaseScopeArgs(ORG_ID, 0))

    result = await expand_and_mark(
        repository, matched, MatchScope(ancestors=True), SessionTreeExpander(), query_builder
    )

    by_id = {row.id: row for row in result}
    assert [row.id for row in result] == ["evt-finish", "node-1", "sess-1"]
    assert by_id["sess-1"].status == session_end_status
    assert by_id["evt-finish"].filter_matched is True
    assert by_id["sess-1"].filter_matched is False


@pytest.mark.asyncio
async def test_session_status_takes_the_latest_session_end_event():
    session = SessionAuditEvent(id="sess-1", session_id=100, kind="session", event_time=NOW, org_id=ORG_ID)
    repository = RecordingRepository(
        [
            session,
            _session_event("evt-end-late", "sess-1", "session_end", "failed", 9),
            _session_event("evt-end-early", "sess-1", "session_end", "completed", 5),
        ]
    )
    query_builder = ScopedQueryBuilder(ScopingPolicy(), BaseScopeArgs(ORG_ID, 0))

    result = await SessionTreeExpander().expand(repository, [session], MatchScope(), query_builder)

    assert [(row.id, row.status) for row in result] == [("sess-1", "failed")]


@pytest.mark.asyncio
async def test_session_status_is_batched_and_stays_none_without_session_end():
    ended = SessionAuditEvent(id="sess-1", session_id=100, kind="session", event_time=NOW, org_id=ORG_ID)
    running = SessionAuditEvent(id="sess-2", session_id=200, kind="session", event_time=NOW, org_id=ORG_ID)
    repository = RecordingRepository(
        [
            ended,
            running,
            _session_event("evt-end-1", "sess-1", "session_end", "completed", 5),
            _session_event("evt-start-2", "sess-2", "session_start", "completed", 1),
        ]
    )
    query_builder = ScopedQueryBuilder(ScopingPolicy(), BaseScopeArgs(ORG_ID, 0))

    result = await SessionTreeExpander().expand(
        repository, [ended, running], MatchScope(), query_builder
    )

    assert [(row.id, row.status) for row in result] == [("sess-1", "completed"), ("sess-2", None)]
    assert ended.status is None
    # One lookup for every session on the page, not one per session.
    assert len(repository.queries) == 1
