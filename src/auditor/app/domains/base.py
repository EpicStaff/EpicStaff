from dataclasses import dataclass
from pathlib import Path
from typing import Generic, Protocol, TypeVar

from app.filtering.ast import FieldSpec, FilterNode
from pydantic import BaseModel

T = TypeVar("T")


@dataclass(frozen=True)
class IndexSpec:
    name: str
    mapping_path: Path
    sort_keys: tuple[tuple[str, str], ...]


class FieldCatalog(Protocol):
    def is_flattened_path(self, field: str) -> bool: ...
    def resolve_alias(self, field: str) -> str: ...
    def field_spec(self, field: str) -> FieldSpec | None: ...
    def computed_field_names(self) -> frozenset[str]: ...


class ComputedField(Protocol):
    name: str

    def combine(self, leaves: list[FilterNode]): ...
    async def resolve(
        self, repository, candidates, *, org_id, retention_days
    ) -> dict[str, float | None]: ...


@dataclass
class BaseScopeArgs:
    org_id: int
    retention_days: int


class MissingScopeError(RuntimeError):
    """Raised instead of silently compiling an unscoped query. BaseAuditEvent.org_id
    is a required field on every event this service stores, so a query compiled
    without an org_id filter term would return every organization's rows. This is
    the single tenancy gate in the service - it must fail closed, not skip the
    filter, whenever org_id is missing (no base_args at all, or a base_args built
    with org_id=None)."""


class ScopingPolicy:
    @staticmethod
    def _get_org_scope(org_id: int) -> dict:
        return {"term": {"org_id": org_id}}

    @staticmethod
    def _get_retention_days_scope(days: int) -> dict:
        return {"range": {"event_time": {"gte": f"now-{days}d"}}}

    def __call__(
        self,
        extra_clauses: list[dict],
        base_args: BaseScopeArgs,
        **kwargs,
    ) -> dict:
        if base_args is None or base_args.org_id is None:
            raise MissingScopeError("Refusing to compile an audit query with no org_id scope.")
        filter_clauses: list[dict] = list(extra_clauses)
        filter_clauses.append(ScopingPolicy._get_org_scope(base_args.org_id))
        if base_args.retention_days and base_args.retention_days > 0:
            filter_clauses.append(ScopingPolicy._get_retention_days_scope(base_args.retention_days))
        for field, value in kwargs.items():
            filter_clauses.append({"term": {field: value}})
        return {"bool": {"filter": filter_clauses}}


class MatchExpander(Protocol):
    async def expand(self, repository, events, scope, *, org_id, retention_days) -> list[dict]: ...


class NullExpander:
    """MatchExpander no-op for a domain with no match-scope expansion
    concept at all."""

    async def expand(self, repository, events, scope, *, org_id, retention_days):
        return events


@dataclass(frozen=True)
class ApiSpec:
    """Request/response shapes + OpenAPI decoration for a domain's search
    and export endpoints. app/controllers/query_routes.py and
    export_routes.py pull these off the domain instead of importing a
    sessions-specific module directly - a second domain plugs in its own
    values here without touching either controller's source."""

    search_request_model: type[BaseModel]
    search_response_model: type[BaseModel]
    export_request_model: type[BaseModel]
    search_description: str
    search_examples: dict[str, dict]


@dataclass(frozen=True)
class AuditDomain(Generic[T]):  # noqa: UP046 - consistent with Generic[T] usage in
    # app/repositories/base.py and shared/audit/{client,writers/base}.py
    name: str
    event_model: type[T]
    index: IndexSpec
    fields: FieldCatalog
    scoping: ScopingPolicy
    computed: tuple[ComputedField, ...]
    expander: MatchExpander
    resource: str
    api: ApiSpec


DEFAULT_SCOPING = ScopingPolicy()
