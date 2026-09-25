"""
Over-fetch/pagination machinery for a computed-field post-filter (e.g.
`duration`) applied in Python on top of an already-compiled OpenSearch
query. Domain-free: works against any ComputedField (see
app/domains/base.py) and whatever condition object its own `combine()`
returned.
"""

from app.domains.base import ComputedField, ScopedQueryBuilder
from app.repositories.base import AuditRepository
from src.shared.models import BaseAuditEvent

OVERFETCH_FACTOR = 4
MAX_OVERFETCH_ROUNDS = 5


async def apply_duration_filter(
    repository: AuditRepository,
    base_query: dict,
    computed_field: ComputedField,
    condition,
    query_builder: ScopedQueryBuilder,
    *,
    size: int,
    cursor: str | None,
) -> tuple[list[BaseAuditEvent], str | None, bool]:
    """
    Over-fetch size*OVERFETCH_FACTOR candidates per
    round, resolve+filter via computed_field/condition, and if short, fetch
    another whole round (capped at MAX_OVERFETCH_ROUNDS) using OpenSearch's
    own next-cursor rather than trying to resume mid-page - a page's cursor
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
    kept: list[BaseAuditEvent] = []
    next_cursor = cursor
    rounds = 0
    exhausted = False

    while len(kept) < size and rounds < MAX_OVERFETCH_ROUNDS:
        rounds += 1
        page, page_cursor = await repository.query(
            base_query, cursor=next_cursor, size=size * OVERFETCH_FACTOR
        )
        if not page:
            exhausted = True
            next_cursor = None
            break

        values = await computed_field.resolve(repository, page, query_builder)
        kept.extend(c for c in page if condition.matches(values.get(c.id)))
        next_cursor = page_cursor

        if page_cursor is None:
            exhausted = True
            break

    partial = not exhausted and len(kept) < size
    return kept, next_cursor, partial
