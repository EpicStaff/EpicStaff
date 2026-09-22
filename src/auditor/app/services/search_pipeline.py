"""
Domain-free 5-stage search/export pipeline: validate -> split computed
leaves -> compile -> fetch -> expand+mark. Both `search` (one cursor page)
and `scan` (paginate to exhaustion) share the validate/split/compile
prefix; they only differ in the fetch stage - `search` returns one page
(optionally overfetching when a computed condition is present, via
app.services.duration_filter.apply_duration_filter), `scan` paginates
until exhausted (used by export, which needs every matching row, not one
page of them).

Collapses what used to be hand-duplicated between
app/controllers/query_routes.py::_run_search and
app/controllers/export_routes.py::_run_export/_collect_all/
_collect_all_matching_duration.
"""

from typing import Any

from app.domains.base import ComputedField, FieldCatalog, MatchExpander
from app.filtering.ast import FilterNode, FilterValidationError, validate_filter_node
from app.filtering.computed import split_computed_leaves
from app.repositories.base import AuditRepository
from app.repositories.compiler import QueryCompiler
from app.services.duration_filter import apply_duration_filter
from app.services.matching import expand_and_mark
from src.shared.models import BaseAuditEvent

SCAN_PAGE_SIZE = 200


class SearchPipeline:
    def __init__(
        self,
        *,
        catalog: FieldCatalog,
        compiler: QueryCompiler,
        computed: tuple[ComputedField, ...],
        expander: MatchExpander,
        event_model: type[BaseAuditEvent],
    ):
        self._catalog = catalog
        self._compiler = compiler
        self._computed = computed
        self._computed_by_name = {field.name: field for field in computed}
        self._expander = expander
        self.event_model = event_model

    def _resolve_condition(
        self, conditions: dict[str, Any]
    ) -> tuple[ComputedField | None, Any]:
        """At most one computed-field condition is supported per request -
        matches every domain today (sessions has exactly one: `duration`).
        Rejected explicitly rather than silently applying only one of
        several, since apply_duration_filter's over-fetch loop is built
        around a single (computed_field, condition) pair."""
        if not conditions:
            return None, None
        if len(conditions) > 1:
            raise FilterValidationError(
                "only one computed-field condition is supported per request, "
                f"got: {sorted(conditions)}"
            )
        ((field_name, condition),) = conditions.items()
        return self._computed_by_name[field_name], condition

    def _compile(
        self, filter_node: FilterNode | None, *, org_id: int, retention_days: int
    ) -> tuple[dict, ComputedField | None, Any]:
        if filter_node is not None:
            validate_filter_node(self._catalog, filter_node)

        remainder_node, conditions = split_computed_leaves(
            filter_node, computed=self._computed
        )
        computed_field, condition = self._resolve_condition(conditions)

        compiled = self._compiler.compile(
            remainder_node, org_id=org_id, retention_days=retention_days
        )
        return compiled, computed_field, condition

    async def search(
        self,
        repository: AuditRepository,
        filter_node: FilterNode | None,
        scope,
        *,
        org_id: int,
        retention_days: int,
        cursor: str | None,
        size: int,
    ) -> tuple[list[BaseAuditEvent], str | None, bool]:
        compiled, computed_field, condition = self._compile(
            filter_node, org_id=org_id, retention_days=retention_days
        )

        if condition is None:
            events, next_cursor = await repository.query(
                compiled, cursor=cursor, size=size
            )
            partial = False
        else:
            events, next_cursor, partial = await apply_duration_filter(
                repository,
                compiled,
                computed_field,
                condition,
                org_id=org_id,
                retention_days=retention_days,
                size=size,
                cursor=cursor,
            )

        events = await expand_and_mark(
            repository,
            events,
            scope,
            self._expander,
            org_id=org_id,
            retention_days=retention_days,
        )
        return events, next_cursor, partial

    async def scan(
        self,
        repository: AuditRepository,
        filter_node: FilterNode | None,
        scope,
        *,
        org_id: int,
        retention_days: int,
    ) -> list[BaseAuditEvent]:
        compiled, computed_field, condition = self._compile(
            filter_node, org_id=org_id, retention_days=retention_days
        )

        if condition is None:
            events = await self._scan_all(repository, compiled)
        else:
            events = await self._scan_matching(
                repository,
                compiled,
                computed_field,
                condition,
                org_id=org_id,
                retention_days=retention_days,
            )

        return await expand_and_mark(
            repository,
            events,
            scope,
            self._expander,
            org_id=org_id,
            retention_days=retention_days,
        )

    async def _scan_all(
        self, repository: AuditRepository, compiled_query: dict
    ) -> list[BaseAuditEvent]:
        events: list[BaseAuditEvent] = []
        cursor = None
        while True:
            page, cursor = await repository.query(
                compiled_query, cursor=cursor, size=SCAN_PAGE_SIZE
            )
            events.extend(page)
            if cursor is None or not page:
                break
        return events

    async def _scan_matching(
        self,
        repository: AuditRepository,
        compiled_query: dict,
        computed_field: ComputedField,
        condition,
        *,
        org_id: int,
        retention_days: int,
    ) -> list[BaseAuditEvent]:
        kept: list[BaseAuditEvent] = []
        cursor = None
        while True:
            page, cursor = await repository.query(
                compiled_query, cursor=cursor, size=SCAN_PAGE_SIZE
            )
            if not page:
                break
            values = await computed_field.resolve(
                repository, page, org_id=org_id, retention_days=retention_days
            )
            kept.extend(c for c in page if condition.matches(values.get(c.id)))
            if cursor is None:
                break
        return kept
