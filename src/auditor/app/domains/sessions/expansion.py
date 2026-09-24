"""
Match-scope expansion for the sessions domain: reshapes which rows come
back once a base search has matched, per the four match-scope toggles.
Session-tree-shaped (kind="session"/"node"/"event", parent_id/session_id
semantics) - not a generic concept, hence living under
app/domains/sessions/ rather than app/services/.
"""

from app.domains.base import ScopedQueryBuilder
from app.repositories.base import AuditRepository
from pydantic import BaseModel, Field
from src.shared.models import SessionAuditEvent

_MAX_ROWS_BEFORE = 20
_FETCH_PAGE_SIZE = 1000


class MatchScope(BaseModel):
    """Structural toggles - change which rows come back around a match,
    never filter conditions themselves. `full_session_history` supersedes
    the other three if set."""

    ancestors: bool = Field(
        default=False,
        description="Pull in the matched row's owning node/session wrapper doc(s), up to 2 hops.",
    )
    children: bool = Field(
        default=False,
        description="A matched session pulls in its whole tree; a matched node pulls in its own events.",
    )
    rows_before: int = Field(
        default=0,
        ge=0,
        le=_MAX_ROWS_BEFORE,
        description=f"Include the N rows immediately preceding each match in the same session (max {_MAX_ROWS_BEFORE}).",
    )
    full_session_history: bool = Field(
        default=False,
        description="Once anything in a session matches, return that session's full unfiltered tree. Supersedes ancestors/children/rows_before.",
    )

    def is_noop(self) -> bool:
        return not (
            self.ancestors or self.children or self.rows_before or self.full_session_history
        )


async def _fetch_all(
    repository: AuditRepository,
    clauses: list[dict],
    query_builder: ScopedQueryBuilder,
) -> list[SessionAuditEvent]:
    """Paginates a follow-up query to exhaustion - these are internal,
    server-built queries (terms/range on ids the base search already
    matched), never a client-influenced free-form query, so an unbounded
    loop here is bounded in practice by how many rows one session/node
    actually has."""
    events: list[SessionAuditEvent] = []
    cursor: str | None = None
    query = query_builder.build(clauses)
    while True:
        page, cursor = await repository.query(query, cursor=cursor, size=_FETCH_PAGE_SIZE)
        events.extend(page)
        if cursor is None or not page:
            break
    return events


async def _expand_full_session_history(
    repository: AuditRepository,
    matched_events: list[SessionAuditEvent],
    query_builder: ScopedQueryBuilder,
) -> list[SessionAuditEvent]:
    session_ids = sorted({e.session_id for e in matched_events})
    if not session_ids:
        return matched_events
    return await _fetch_all(
        repository,
        [{"terms": {"session_id": session_ids}}],
        query_builder,
    )


async def _expand_ancestors(
    repository: AuditRepository,
    matched_events: list[SessionAuditEvent],
    query_builder: ScopedQueryBuilder,
) -> list[SessionAuditEvent]:
    """Walks parent_id upward, batched (not N+1). Session -> node -> event
    is only 2 hops max, so this never needs to recurse arbitrarily deep."""
    parent_ids = sorted({e.parent_id for e in matched_events if e.parent_id})
    if not parent_ids:
        return []
    wrappers = await _fetch_all(
        repository,
        [{"terms": {"id": parent_ids}}],
        query_builder,
    )
    grandparent_ids = sorted({w.parent_id for w in wrappers if w.parent_id})
    grandparents = (
        await _fetch_all(
            repository,
            [{"terms": {"id": grandparent_ids}}],
            query_builder,
        )
        if grandparent_ids
        else []
    )
    return wrappers + grandparents


async def _expand_children(
    repository: AuditRepository,
    matched_events: list[SessionAuditEvent],
    query_builder: ScopedQueryBuilder,
) -> list[SessionAuditEvent]:
    """A matched session's children are its whole tree (session_id scan);
    a matched node's children are its own event rows (parent_id scan). A
    matched event has no further children - its own `details` is already
    the full row, nothing more to fetch. Batched per kind, not per row."""
    extra: list[SessionAuditEvent] = []

    session_matches = [e for e in matched_events if e.kind == "session"]
    if session_matches:
        session_ids = sorted({e.session_id for e in session_matches})
        extra.extend(
            await _fetch_all(
                repository,
                [{"terms": {"session_id": session_ids}}],
                query_builder,
            )
        )

    node_matches = [e for e in matched_events if e.kind == "node"]
    if node_matches:
        node_ids = sorted({e.id for e in node_matches})
        extra.extend(
            await _fetch_all(
                repository,
                [{"terms": {"parent_id": node_ids}}],
                query_builder,
            )
        )

    return extra


async def _expand_rows_before(
    repository: AuditRepository,
    matched_events: list[SessionAuditEvent],
    rows_before: int,
    query_builder: ScopedQueryBuilder,
) -> list[SessionAuditEvent]:
    """One extra query per match (OpenSearch has no native "N rows before X"
    primitive) - same session, event_time <= the match's own, same fixed
    sort, +1 to account for the match itself being included by `lte` and
    then dropped by id. Note: ties in event_time (same session, same
    microsecond) could shift the exact boundary by one row - acceptable
    given real event_time values have microsecond resolution in practice."""
    extra: list[SessionAuditEvent] = []
    for event in matched_events:
        clauses = [
            {"term": {"session_id": event.session_id}},
            {"range": {"event_time": {"lte": event.event_time.isoformat()}}},
        ]
        query = query_builder.build(clauses)
        page, _ = await repository.query(query, cursor=None, size=rows_before + 1)
        extra.extend(row for row in page if row.id != event.id)
    return extra


async def expand_matches(
    repository: AuditRepository,
    matched_events: list[SessionAuditEvent],
    match_scope: MatchScope,
    query_builder: ScopedQueryBuilder,
) -> list[SessionAuditEvent]:
    if not matched_events or match_scope.is_noop():
        return matched_events

    if match_scope.full_session_history:
        # Supersedes every other toggle - once anything in a session
        # matches, the whole session's tree is the answer; rows_before/
        # ancestors/children would all be redundant subsets of this.
        return _dedupe_and_sort(
            await _expand_full_session_history(repository, matched_events, query_builder)
        )

    extra: list[SessionAuditEvent] = []
    if match_scope.ancestors:
        extra.extend(await _expand_ancestors(repository, matched_events, query_builder))
    if match_scope.children:
        extra.extend(await _expand_children(repository, matched_events, query_builder))
    if match_scope.rows_before > 0:
        extra.extend(
            await _expand_rows_before(
                repository,
                matched_events,
                match_scope.rows_before,
                query_builder,
            )
        )

    return _dedupe_and_sort(matched_events + extra)


def _dedupe_and_sort(events: list[SessionAuditEvent]) -> list[SessionAuditEvent]:
    # TODO: derive from IndexSpec.sort_keys instead of a hardcoded copy of
    # the fixed sort order (same knowledge already lives in
    # OpenSearchAuditRepository._execute) - flagged, not fixed, during the
    # domain-abstraction restructure.
    by_id: dict[str, SessionAuditEvent] = {e.id: e for e in events}
    return sorted(by_id.values(), key=lambda e: (e.event_time, e.id), reverse=True)


class SessionTreeExpander:
    """MatchExpander implementation (see app/domains/base.py) for the
    sessions domain."""

    async def expand(
        self, repository, events, match_scope: MatchScope, query_builder: ScopedQueryBuilder
    ) -> list[SessionAuditEvent]:
        return await expand_matches(repository, events, match_scope, query_builder)
