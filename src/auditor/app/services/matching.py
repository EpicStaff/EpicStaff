"""
Domain-free match-scope orchestration: expand via whatever MatchExpander a
domain supplies, then flag which rows in the final list were original
matches vs. pulled in by expansion. Lives outside the repository (its
contract is "one query in, one page out"; this needs multiple round-trips)
and outside the AST/compiler (match-scope toggles are structural - they
change which rows come back, not filter conditions).
"""

from app.domains.base import MatchExpander
from app.repositories.base import AuditRepository
from src.shared.models import BaseAuditEvent


async def mark_filter_matched(
    events: list[BaseAuditEvent], matched_ids: set[str]
) -> list[BaseAuditEvent]:
    for event in events:
        event.filter_matched = event.id in matched_ids
    return events


async def expand_and_mark(
    repository: AuditRepository,
    events: list[BaseAuditEvent],
    scope,
    expander: MatchExpander,
    *,
    org_id: int,
    retention_days: int,
) -> list[BaseAuditEvent]:
    """Shared by search and export: expand per scope, then flag which rows
    in the final list were original matches vs. pulled in by expansion.
    id-based (not identity-based) because full-history-style expansion can
    re-fetch fresh objects for the same ids - see mark_filter_matched."""
    matched_ids = {e.id for e in events}
    if not scope.is_noop():
        events = await expander.expand(
            repository, events, scope, org_id=org_id, retention_days=retention_days
        )
    return await mark_filter_matched(events, matched_ids)
