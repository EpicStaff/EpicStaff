"""
Shared test doubles for auditor tests. Not itself a test module (no
`test_` prefix) - pytest's default discovery never collects this file,
it's only ever imported by the real test modules.
"""

import operator
from datetime import datetime

from src.shared.models import SessionAuditEvent

_RANGE_OPERATORS = {"lt": operator.lt, "lte": operator.le, "gt": operator.gt, "gte": operator.ge}


def _range_matches(event: SessionAuditEvent, clause: dict) -> bool:
    (field, bounds), = clause["range"].items()
    actual = getattr(event, field, None)
    if actual is None:
        return False
    for op, bound in bounds.items():
        # Datetime fields arrive as isoformat strings in the clause. Date
        # math such as the retention scope's "now-10d" is not supported and
        # raises here rather than silently matching.
        if isinstance(actual, datetime):
            bound = datetime.fromisoformat(bound)
        if not _RANGE_OPERATORS[op](actual, bound):
            return False
    return True


def _clause_matches(event: SessionAuditEvent, clause: dict) -> bool:
    if "term" in clause:
        (field, value), = clause["term"].items()
        return getattr(event, field, None) == value
    if "terms" in clause:
        (field, values), = clause["terms"].items()
        return getattr(event, field, None) in values
    if "range" in clause:
        return _range_matches(event, clause)
    # bool/wildcard/etc. clauses aren't exercised by the current tests built
    # on this fake - treat as always-matching rather than trying to fully
    # reimplement the compiler's semantics here. KNOWN LIMITATION: a test
    # whose correctness depends on one of those clauses would pass even if
    # the clause were wrong, unless _clause_matches is extended first.
    return True


class InMemoryFakeRepository:
    """Stands in for SessionAuditRepository - evaluates the compiled
    `{"bool": {"filter": [...]}}` query against an in-memory event list.
    Real enough to drive match_scope's ancestors/children/rows_before/
    full_session_history follow-up queries (simple term/terms/range
    lookups), without needing real OpenSearch.

    Paginates like the real repository: a `cursor` is just the string form
    of an offset into the sorted match list, and a page hands back a
    non-None `next_cursor` whenever more matches remain past `size`. Every
    test that only ever seeds fewer rows than `size` still sees the old
    single-page behavior (`cursor=None` immediately) for free - pagination
    only kicks in once a test actually seeds more rows than one page.

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

        offset = int(cursor) if cursor is not None else 0
        page = matches[offset : offset + size]
        next_offset = offset + size
        next_cursor = str(next_offset) if next_offset < len(matches) else None

        return [e.model_copy(deep=True) for e in page], next_cursor
