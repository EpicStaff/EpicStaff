from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, Protocol, TypeVar

from app.filtering.ast import FieldSpec, FilterNode
from app.filtering.constants import FLATTENED_OPS
from pydantic import BaseModel
from src.shared.models import BaseAuditEvent

EventT = TypeVar("EventT", bound=BaseAuditEvent)


@dataclass(frozen=True)
class IndexSpec:
    name: str
    mapping_path: Path
    sort_keys: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class FreeTextFields:
    """Where a free-text (`__text__`) term is searched: case-insensitive
    wildcard over `wildcard_fields`, relevance `query_string` over
    `query_string_fields` (patterns such as `details.*` are allowed)."""

    wildcard_fields: tuple[str, ...] = ()
    query_string_fields: tuple[str, ...] = ()


class FieldCatalog(Protocol):
    def is_flattened_path(self, field: str) -> bool: ...
    def resolve_alias(self, field: str) -> str: ...
    def field_spec(self, field: str) -> FieldSpec | None: ...
    def computed_field_names(self) -> frozenset[str]: ...
    def free_text_fields(self) -> FreeTextFields: ...
    def wildcard_subfield(self, field: str) -> str | None: ...


class DictFieldCatalog:
    """FieldCatalog backed by plain lookup tables. Every lookup is
    case-insensitive on the field name."""

    def __init__(
        self,
        *,
        known_fields: Mapping[str, FieldSpec],
        aliases: Mapping[str, str] | None = None,
        flat_roots: frozenset[str] = frozenset(),
        flattened_path_spec: FieldSpec = FieldSpec(FLATTENED_OPS),
        free_text: FreeTextFields = FreeTextFields(),
        wildcard_subfields: Mapping[str, str] | None = None,
    ):
        self._known_fields = dict(known_fields)
        self._aliases = dict(aliases or {})
        self._flat_roots = flat_roots
        self._flattened_path_spec = flattened_path_spec
        self._free_text = free_text
        self._wildcard_subfields = dict(wildcard_subfields or {})

    def is_flattened_path(self, field: str) -> bool:
        return field.lower().split(".", 1)[0] in self._flat_roots

    def resolve_alias(self, field: str) -> str:
        return self._aliases.get(field.lower(), field)

    def field_spec(self, field: str) -> FieldSpec | None:
        lower = field.lower()
        if lower in self._known_fields:
            return self._known_fields[lower]
        if self.is_flattened_path(lower):
            return self._flattened_path_spec
        return None

    def computed_field_names(self) -> frozenset[str]:
        return frozenset(name for name, spec in self._known_fields.items() if spec.computed)

    def free_text_fields(self) -> FreeTextFields:
        return self._free_text

    def wildcard_subfield(self, field: str) -> str | None:
        return self._wildcard_subfields.get(field.lower())


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
        filter_clauses.append(self._get_org_scope(base_args.org_id))
        if base_args.retention_days and base_args.retention_days > 0:
            filter_clauses.append(self._get_retention_days_scope(base_args.retention_days))
        for field, value in kwargs.items():
            filter_clauses.append({"term": {field: value}})
        return {"bool": {"filter": filter_clauses}}


@dataclass(frozen=True)
class ScopedQueryBuilder:
    """A domain's ScopingPolicy bound to one request's org/retention scope.
    Handed to expanders and computed fields so their follow-up queries are
    scoped by the same policy as the main query, never a hardcoded default."""

    policy: ScopingPolicy
    args: BaseScopeArgs

    def build(self, clauses: list[dict]) -> dict:
        return self.policy(clauses, self.args)


class ComputedField(Protocol):
    name: str

    def combine(self, leaves: list[FilterNode]): ...
    async def resolve(
        self, repository, candidates, query_builder: ScopedQueryBuilder
    ) -> dict[str, float | None]: ...


class MatchExpander(Protocol):
    async def expand(
        self, repository, events, match_scope, query_builder: ScopedQueryBuilder
    ) -> list: ...


class NullExpander:
    """MatchExpander no-op for a domain with no match-scope expansion
    concept at all."""

    async def expand(self, repository, events, match_scope, query_builder):
        return events


@dataclass(frozen=True)
class ApiSpec:
    """Request/response shapes + OpenAPI decoration for a domain's search
    and export endpoints. A request model may omit `match_scope` entirely
    when the domain has no expansion concept."""

    search_request_model: type[BaseModel]
    search_response_model: type[BaseModel]
    export_request_model: type[BaseModel]
    search_description: str
    search_examples: dict[str, dict]


@dataclass(frozen=True)
class AuditDomain(Generic[EventT]):  # noqa: UP046 - matches Generic usage in app/repositories/base.py
    name: str
    event_model: type[EventT]
    index: IndexSpec
    fields: FieldCatalog
    scoping: ScopingPolicy
    computed: tuple[ComputedField, ...]
    expander: MatchExpander
    resource: str
    api: ApiSpec

    def __post_init__(self) -> None:
        # The AST splitter keys on `computed`, validation keys on the catalog's
        # FieldSpec(computed=True). A mismatch would send a computed leaf to the
        # OpenSearch compiler as a plain term on a nonexistent field and
        # silently return zero rows, so it must fail at import time instead.
        declared = self.fields.computed_field_names()
        implemented = frozenset(field.name for field in self.computed)
        if declared != implemented:
            raise ValueError(
                f"Audit domain {self.name!r}: fields marked computed in the catalog "
                f"{sorted(declared)} do not match its ComputedField implementations "
                f"{sorted(implemented)}"
            )


DEFAULT_SCOPING = ScopingPolicy()
