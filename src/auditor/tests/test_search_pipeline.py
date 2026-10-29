from datetime import datetime, timedelta, timezone

import pytest

from app.domains.sessions.domain import SESSIONS
from app.domains.sessions.schemas import SessionSearchRequest
from app.services.search_pipeline import SearchPipeline
from src.shared.models import SessionAuditEvent
from tests._fakes import InMemoryFakeRepository


def _make_event(id_: str) -> SessionAuditEvent:
    return SessionAuditEvent(
        id=id_, session_id=1, kind="event", event_time=datetime.now(timezone.utc), org_id=7
    )


class _MidScanEmptyPageRepository:
    """Simulates a repository whose middle page comes back empty (e.g. every
    document on that page failed to deserialize) while OpenSearch's cursor
    still points at further, non-empty pages."""

    def __init__(self, pages: list[tuple[list[SessionAuditEvent], str | None]]):
        self._pages = pages
        self.calls = 0

    async def query(self, compiled_query: dict, cursor: str | None = None, size: int = 200):
        page = self._pages[self.calls]
        self.calls += 1
        return page


@pytest.mark.asyncio
async def test_scan_all_does_not_stop_on_an_empty_page_with_a_follow_up_cursor():
    pipeline = SearchPipeline.from_domain(SESSIONS)
    repository = _MidScanEmptyPageRepository(
        [
            ([_make_event("e1"), _make_event("e2")], "cursor-1"),
            ([], "cursor-2"),  # empty page, but more pages remain
            ([_make_event("e3")], None),
        ]
    )

    collected = []
    async for page in pipeline.scan(repository, None, None, org_id=7, retention_days=0):
        collected.extend(page)

    assert [e.id for e in collected] == ["e1", "e2", "e3"]


def _tree_events() -> list[SessionAuditEvent]:
    """A session tree (session -> node -> event) plus another session's event."""
    now = datetime.now(timezone.utc)

    def event(event_id, kind, seconds, parent_id="", session_id=100):
        return SessionAuditEvent(
            id=event_id, parent_id=parent_id, session_id=session_id, kind=kind,
            status="failed", event_time=now + timedelta(seconds=seconds), org_id=7,
        )

    return [
        event("sess-1", "session", 0),
        event("node-1", "node", 1, "sess-1"),
        event("evt-1", "event", 2, "node-1"),
        event("evt-other", "event", 0, session_id=200),
    ]


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            {"filters": {"field": "session_id", "op": "equals", "value": 100}},
            {"sess-1": True, "node-1": True, "evt-1": True},
        ),
        (
            {
                "filters": {"field": "id", "op": "equals", "value": "sess-1"},
                "match_scope": {"children": True},
            },
            {"sess-1": True, "node-1": False, "evt-1": False},
        ),
        (
            # The history is re-fetched as new objects; matches are recognised by id.
            {
                "filters": {"field": "id", "op": "equals", "value": "evt-1"},
                "match_scope": {"full_session_history": True},
            },
            {"sess-1": False, "node-1": False, "evt-1": True},
        ),
    ],
    ids=["no-match-scope", "children", "full-session-history"],
)
@pytest.mark.asyncio
async def test_match_scope_expansion_flags_only_the_rows_the_filter_matched(body, expected):
    request = SessionSearchRequest(**body)

    events, _, _ = await SearchPipeline.from_domain(SESSIONS).search(
        InMemoryFakeRepository(_tree_events()),
        request.resolve_filter_node(),
        request.match_scope,
        org_id=7,
        retention_days=0,
        cursor=None,
        size=request.size,
    )

    assert {event.id: event.filter_matched for event in events} == expected
