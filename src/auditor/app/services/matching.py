"""
Domain-free match-scope orchestration: expand via whatever MatchExpander a
domain supplies, then flag which rows in the final list were original
matches vs. pulled in by expansion. Lives outside the repository (its
contract is "one query in, one page out"; this needs multiple round-trips)
and outside the AST/compiler (match-scope toggles are structural - they
change which rows come back, not filter conditions).
"""

from app.domains.base import MatchExpander, ScopedQueryBuilder
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
    match_scope,
    expander: MatchExpander,
    query_builder: ScopedQueryBuilder,
) -> list[BaseAuditEvent]:
    """Shared by search and export: expand per match_scope, then flag which
    rows in the final list were original matches vs. pulled in by expansion.
    id-based (not identity-based) because full-history-style expansion can
    re-fetch fresh objects for the same ids - see mark_filter_matched.

    `match_scope=None` means the domain has no expansion concept. Whether a
    non-None scope is a no-op is the expander's own decision, so this never
    requires a scope object to implement any particular method."""
    matched_ids = {event.id for event in events}
    if match_scope is not None:
        events = await expander.expand(repository, events, match_scope, query_builder)
    return await mark_filter_matched(events, matched_ids)
