"""
`duration` - the sessions domain's only computed field. Not indexed (see
plan §9.4/§9.6): a node's duration is the diff between its Start event and
its Finish/Error event (both kind="event" rows sharing parent_id == the
node wrapper's own id); a session's is the same one level up (Session
Start/Session End sharing parent_id == the session identity doc's own
id). Neither exists as an OpenSearch field, so filtering on it can never
be pushed into the compiled query - app/filtering/computed.py splits it
out of the AST before compilation, and DurationField (below) is what
combines/resolves it against whatever candidates the rest of the filter
already narrowed down to.
"""

from typing import Any, NamedTuple

from app.domains.base import ScopedQueryBuilder
from app.filtering.ast import FilterNode, FilterValidationError
from src.shared.models import SessionAuditEvent

_START_MARKERS = frozenset({"start", "session_start"})
_TERMINAL_MARKERS = frozenset({"finish", "error", "session_end"})


class DurationCondition(NamedTuple):
    equals: float | None = None
    gt: float | None = None
    gte: float | None = None
    lt: float | None = None
    lte: float | None = None
    is_empty: bool = False
    is_not_empty: bool = False

    def matches(self, duration: float | None) -> bool:
        if self.is_empty:
            return duration is None
        if self.is_not_empty:
            return duration is not None
        if duration is None:
            return False
        if self.equals is not None and duration != self.equals:
            return False
        if self.gt is not None and not (duration > self.gt):
            return False
        if self.gte is not None and not (duration >= self.gte):
            return False
        if self.lt is not None and not (duration < self.lt):
            return False
        return self.lte is None or duration <= self.lte


def _combine_duration_leaves(leaves: list[FilterNode]) -> DurationCondition:
    kwargs: dict[str, Any] = {}
    for leaf in leaves:
        op = leaf["op"]
        if op == "is_empty":
            kwargs["is_empty"] = True
        elif op == "is_not_empty":
            kwargs["is_not_empty"] = True
        elif op in ("equals", "gt", "gte", "lt", "lte"):
            if op in kwargs:
                raise FilterValidationError(f"duration: op {op!r} specified more than once")
            try:
                kwargs[op] = float(leaf["value"])
            except (KeyError, TypeError, ValueError) as exc:
                raise FilterValidationError(
                    f"duration: op {op!r} requires a numeric value"
                ) from exc
        else:
            raise FilterValidationError(f"duration: unsupported op {op!r}")
    if ("is_empty" in kwargs or "is_not_empty" in kwargs) and len(kwargs) > 1:
        raise FilterValidationError(
            "duration: is_empty/is_not_empty cannot be combined with other duration conditions"
        )
    return DurationCondition(**kwargs)


def compute_duration(events: list[SessionAuditEvent]) -> float | None:
    """events: every kind="event" row sharing one parent_id (a node or
    session wrapper's own id). Requires a genuine start marker AND a
    genuine terminal marker to both exist - `None` ("empty"/in-flight)
    otherwise, not just "fewer than 2 rows exist so far" (a node emits many
    non-terminal custom-message events between Start and Finish/Error).
    Keyed entirely on details.message_type (set by SessionAuditWriter for
    both node- and session-level events) - never on `name`, which is a
    free-form/display field elsewhere and must not double as a machine
    sentinel here."""
    start_time = None
    end_time = None
    for event in events:
        message_type = (event.details or {}).get("message_type")
        is_earlier_start = start_time is None or event.event_time < start_time
        is_later_end = end_time is None or event.event_time > end_time
        if message_type in _START_MARKERS and is_earlier_start:
            start_time = event.event_time
        elif message_type in _TERMINAL_MARKERS and is_later_end:
            end_time = event.event_time
    if start_time is None or end_time is None:
        return None
    return (end_time - start_time).total_seconds()


async def _resolve_durations(
    repository,
    candidates: list[SessionAuditEvent],
    query_builder: ScopedQueryBuilder,
) -> dict[str, float | None]:
    """Batch-resolves every candidate's duration in one query (not N+1). A
    candidate that is itself a kind="event" row belongs to some node/session
    - its own parent_id is the id to pair Start/Finish under. A candidate
    that is a kind="node"/"session" wrapper IS that id itself."""
    target_id_by_candidate: dict[str, str] = {
        c.id: (c.parent_id if c.kind == "event" else c.id) for c in candidates
    }
    parent_ids = sorted(set(target_id_by_candidate.values()))
    if not parent_ids:
        return {c.id: None for c in candidates}

    query = query_builder.build([{"terms": {"parent_id": parent_ids}}])
    events_by_parent: dict[str, list[SessionAuditEvent]] = {pid: [] for pid in parent_ids}
    cursor: str | None = None
    while True:
        page, cursor = await repository.query(query, cursor=cursor, size=1000)
        for event in page:
            events_by_parent.setdefault(event.parent_id, []).append(event)
        if cursor is None or not page:
            break

    duration_cache: dict[str, float | None] = {
        pid: compute_duration(events) for pid, events in events_by_parent.items()
    }
    return {cid: duration_cache.get(target_id) for cid, target_id in target_id_by_candidate.items()}


class DurationField:
    """ComputedField implementation (see app/domains/base.py) for the
    sessions domain's `duration` field."""

    name = "duration"

    def combine(self, leaves: list[FilterNode]) -> DurationCondition:
        return _combine_duration_leaves(leaves)

    async def resolve(
        self, repository, candidates, query_builder: ScopedQueryBuilder
    ) -> dict[str, float | None]:
        return await _resolve_durations(repository, candidates, query_builder)


SESSIONS_COMPUTED = (DurationField(),)
