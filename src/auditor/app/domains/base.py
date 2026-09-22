from dataclasses import dataclass
from typing import Generic, TypeVar, Protocol
from pathlib import Path

from app.filtering.ast import FilterNode, FieldSpec


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
    org_id: int | None = None
    retention_days: int | None = None


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
        base_args: BaseScopeArgs | None = None,
        **kwargs,
    ) -> dict:
        filter_clauses: list[dict] = list(extra_clauses)
        if base_args:
            if base_args.org_id is not None:
                filter_clauses.append(ScopingPolicy._get_org_scope(base_args.org_id))
            if base_args.retention_days is not None and base_args.retention_days > 0:
                filter_clauses.append(
                    ScopingPolicy._get_retention_days_scope(base_args.retention_days)
                )
        for field, value in kwargs.items():
            filter_clauses.append({"term": {field: value}})
        return {"bool": {"filter": filter_clauses}}


class MatchExpander(Protocol):
    async def expand(
        self, repository, events, scope, *, org_id, retention_days
    ) -> list[dict]: ...


class NullExpander:
    """MatchExpander no-op for a domain with no match-scope expansion
    concept at all."""

    async def expand(self, repository, events, scope, *, org_id, retention_days):
        return events


@dataclass(frozen=True)
class AuditDomain(Generic[T]):
    name: str
    event_model: type[T]
    index: IndexSpec
    fields: FieldCatalog
    scoping: ScopingPolicy
    computed: tuple[ComputedField, ...]
    expander: MatchExpander
    resource: str


DEFAULT_SCOPING = ScopingPolicy()
