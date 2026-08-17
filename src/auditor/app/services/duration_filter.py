"""
Duration is computed, not indexed (see plan §9.4/§9.6 discussion): a node's
duration is the diff between its Start event and its Finish/Error event
(both kind="event" rows sharing parent_id == the node wrapper's own id);
a session's is the same one level up (Session Start/Session End sharing
parent_id == the session identity doc's own id). Neither exists as an
OpenSearch field, so filtering on `duration` can never be pushed into the
compiled query - it has to be split out of the AST and evaluated in Python,
against whatever candidates the rest of the filter already narrowed down to.
"""

from typing import Any, NamedTuple

from app.filtering.ast import FilterNode, FilterValidationError, iter_leaves
from app.repositories.base import SessionAuditRepository
from app.repositories.opensearch_query_compiler import scoped_query
from src.shared.models import SessionAuditEvent

OVERFETCH_FACTOR = 4
MAX_OVERFETCH_ROUNDS = 5

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
        if self.lte is not None and not (duration <= self.lte):
            return False
        return True


def _is_duration_leaf(node: FilterNode) -> bool:
    return node.get("field", "").lower() == "duration"


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
            kwargs[op] = float(leaf["value"])
        else:
            raise FilterValidationError(f"duration: unsupported op {op!r}")
    if ("is_empty" in kwargs or "is_not_empty" in kwargs) and len(kwargs) > 1:
        raise FilterValidationError(
            "duration: is_empty/is_not_empty cannot be combined with other duration conditions"
        )
    return DurationCondition(**kwargs)


def _split(node: FilterNode) -> tuple[FilterNode | None, list[FilterNode]]:
    op = node.get("op")

    if op == "and":
        remainders: list[FilterNode] = []
        duration_leaves: list[FilterNode] = []
        for child in node["children"]:
            child_remainder, child_durations = _split(child)
            if child_remainder is not None:
                remainders.append(child_remainder)
            duration_leaves.extend(child_durations)
        if not remainders:
            remainder = None
        elif len(remainders) == 1:
            remainder = remainders[0]
        else:
            remainder = {"op": "and", "children": remainders}
        return remainder, duration_leaves

    if op in ("or", "not"):
        # Correctly evaluating "... or duration > 5" (or a negated duration
        # condition) against a computed field needs full boolean-tree
        # evaluation over the whole candidate set post-fetch - materially
        # bigger scope than "AND one post-filter on top of the OpenSearch
        # query". Rejected outright rather than silently mishandled.
        if any(_is_duration_leaf(leaf) for leaf in iter_leaves(node)):
            raise FilterValidationError(
                f"'duration' cannot be combined with '{op}' - only a top-level "
                "AND of duration conditions is supported"
            )
        return node, []

    if _is_duration_leaf(node):
        return None, [node]
    return node, []


def split_duration_filter(node: FilterNode | None) -> tuple[FilterNode | None, DurationCondition | None]:
    """Extracts every `duration` leaf out of the AST (they must only ever
    appear directly under a top-level `and`, never under `or`/`not` -
    enforced above), combines them into one DurationCondition, and returns
    the remainder AST with those leaves removed."""
    if node is None:
        return None, None
    remainder, duration_leaves = _split(node)
    if not duration_leaves:
        return remainder, None
    return remainder, _combine_duration_leaves(duration_leaves)


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
        if message_type in _START_MARKERS:
            if start_time is None or event.event_time < start_time:
                start_time = event.event_time
        elif message_type in _TERMINAL_MARKERS:
            if end_time is None or event.event_time > end_time:
                end_time = event.event_time
    if start_time is None or end_time is None:
        return None
    return (end_time - start_time).total_seconds()


async def _resolve_durations(
    repository: SessionAuditRepository,
    candidates: list[SessionAuditEvent],
    *,
    org_id: int,
    retention_days: int,
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

    query = scoped_query([{"terms": {"parent_id": parent_ids}}], org_id=org_id, retention_days=retention_days)
    events_by_parent: dict[str, list[SessionAuditEvent]] = {pid: [] for pid in parent_ids}
    cursor: str | None = None
    while True:
        page, cursor = await repository.query_ast(query, cursor=cursor, size=1000)
        for event in page:
            events_by_parent.setdefault(event.parent_id, []).append(event)
        if cursor is None or not page:
            break

    duration_cache: dict[str, float | None] = {
        pid: compute_duration(events) for pid, events in events_by_parent.items()
    }
    return {cid: duration_cache.get(target_id) for cid, target_id in target_id_by_candidate.items()}


async def apply_duration_filter(
    repository: SessionAuditRepository,
    base_query: dict,
    duration_cond: DurationCondition,
    *,
    org_id: int,
    retention_days: int,
    size: int,
    cursor: str | None,
) -> tuple[list[SessionAuditEvent], str | None, bool]:
    """
    Over-fetch size*OVERFETCH_FACTOR candidates per
    round, resolve+filter by duration, and if short, fetch another whole
    round (capped at MAX_OVERFETCH_ROUNDS) using OpenSearch's own
    next-cursor rather than trying to resume mid-page - a page's cursor
    only makes sense at its own boundary. 
    Deliberate consequence: this may return slightly MORE
    than `size` matches (never fewer, unless truly exhausted or the round
    cap is hit) when a single round's matches overshoot the remaining need
    - trimming those extras would silently drop already-matched results
    with no way to resume from where the trim happened, which is worse
    than returning a bit more than asked. Returns (events, next_cursor,
    partial) - `partial=True` only when the round cap was hit with still
    too few matches (a resumable cursor is still returned in that case).
    """
    kept: list[SessionAuditEvent] = []
    next_cursor = cursor
    rounds = 0
    exhausted = False

    while len(kept) < size and rounds < MAX_OVERFETCH_ROUNDS:
        rounds += 1
        page, page_cursor = await repository.query_ast(base_query, cursor=next_cursor, size=size * OVERFETCH_FACTOR)
        if not page:
            exhausted = True
            next_cursor = None
            break

        durations = await _resolve_durations(repository, page, org_id=org_id, retention_days=retention_days)
        kept.extend(c for c in page if duration_cond.matches(durations.get(c.id)))
        next_cursor = page_cursor

        if page_cursor is None:
            exhausted = True
            break

    partial = not exhausted and len(kept) < size
    return kept, next_cursor, partial
