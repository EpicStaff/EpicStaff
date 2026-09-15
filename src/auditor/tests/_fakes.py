"""
Shared test doubles for auditor tests. Not itself a test module (no
`test_` prefix) - pytest's default discovery never collects this file,
it's only ever imported by the real test modules.
"""

from src.shared.models import SessionAuditEvent


def _clause_matches(event: SessionAuditEvent, clause: dict) -> bool:
    if "term" in clause:
        (field, value), = clause["term"].items()
        return getattr(event, field, None) == value
    if "terms" in clause:
        (field, values), = clause["terms"].items()
        return getattr(event, field, None) in values
    # range/bool/wildcard/etc. clauses aren't exercised by the current tests
    # built on this fake - treat as always-matching rather than trying to
    # fully reimplement the compiler's semantics here. KNOWN LIMITATION: this
    # means a `range` clause (e.g. the `event_time <= ...` upper bound that
    # match_scope._expand_rows_before builds) is silently ignored - a
    # rows_before test reusing this fake would pass even if the time-bound
    # filtering were broken, unless _clause_matches is extended first.
    return True


class InMemoryFakeRepository:
    """Stands in for SessionAuditRepository - evaluates the compiled
    `{"bool": {"filter": [...]}}` query against an in-memory event list.
    Real enough to drive match_scope's ancestors/children/rows_before/
    full_session_history follow-up queries (all of which are simple
    term/terms lookups), without needing real OpenSearch.

    Always returns a single page (cursor=None) - every existing fake
    repository in this test suite does the same, and the event counts used
    in these tests never need pagination.

    Returns fresh `model_copy()` instances on every query, never the
    stored objects themselves - this mirrors real deserialization (each
    OpenSearch round-trip produces brand-new SessionAuditEvent instances).
    mark_filter_matched itself only ever compares by `.id` against a plain
    `set[str]` (never object identity), so returning copies isn't needed to
    make that comparison correct - it's here so a full_session_history test
    reusing this fake looks like the real repository boundary (id survives
    the round-trip, the object itself doesn't) rather than silently relying
    on the same instance being reused end to end.
    """

    def __init__(self, events: list[SessionAuditEvent]):
        self._events = events

    async def query(self, query: dict, cursor: str | None = None, size: int = 50):
        clauses = query["bool"]["filter"]
        matches = [
            e for e in self._events if all(_clause_matches(e, c) for c in clauses)
        ]
        matches.sort(key=lambda e: (e.event_time, e.id), reverse=True)
        return [e.model_copy(deep=True) for e in matches[:size]], None
