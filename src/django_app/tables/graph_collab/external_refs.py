"""Detect and null a live collab payload's stale outward (non-graph) FK/M2M
refs — see ExternalRefField in tables.services.graph_bulk_save_service.registry
for the declarative list of which node fields point outside the graph
(LLMConfig, NgrokWebhookConfig, a subgraph Graph, Secret, AgentDefinition,
Surface).

Why this exists: deleting a referenced row fires the model's
SET_NULL/SET_DEFAULT immediately, but the live Redis snapshot still holds the
old pk. On the next autosave flush that stale pk fails the bulk-save
serializer's PrimaryKeyRelatedField validation ("Invalid pk … object does not
exist") and wedges the ENTIRE graph's autosave in an infinite poison-retry —
reconcile_against_db's existing node/edge/routing pruning does not cover it,
since the node row itself still exists.
"""

from collections import defaultdict
from dataclasses import dataclass

from tables.services.graph_bulk_save_service.registry import (
    NODE_TYPE_REGISTRY,
    ExternalRefField,
    ExternalRefKind,
)
from utils.logger import logger


@dataclass(frozen=True)
class DeadRef:
    """One stale outward ref found (and already nulled in the payload) by
    find_dead_external_refs — enough information for the caller to also null
    the same ref out of the live Redis snapshot and broadcast the change."""

    list_key: str
    node_id: int | None
    ref_field: ExternalRefField
    old_pk: int
    reason: str  # "deleted" | "cross_org"
    temp_id: str | None = None

    @property
    def node_key(self) -> int | str:
        """Whichever identifier this node is addressable by — a persisted int
        ``id``, or the ``temp_id`` of a node not yet flushed."""
        return self.node_id if self.node_id is not None else self.temp_id  # type: ignore[return-value]

    @property
    def top_level_field(self) -> str:
        return self.ref_field.top_level_field

    @property
    def field_path(self) -> str:
        if self.ref_field.top_level_field == self.ref_field.leaf_field:
            return self.ref_field.top_level_field
        return f"{self.ref_field.top_level_field}.{self.ref_field.leaf_field}"


def null_ref_in_entry(entry: dict, ref_field: ExternalRefField, pk: int) -> None:
    """Null *pk* out of *entry* per *ref_field*'s shape. Idempotent — a no-op
    if the value is already absent. Shared by the payload-nulling pass here
    and the live-snapshot mirror in GraphLiveStateService.null_external_refs,
    so both operate on identical semantics."""
    kind = ref_field.kind

    if kind is ExternalRefKind.SCALAR:
        if entry.get(ref_field.leaf_field) == pk:
            entry[ref_field.leaf_field] = None

    elif kind is ExternalRefKind.SCALAR_LIST:
        values = entry.get(ref_field.leaf_field)
        if isinstance(values, list) and pk in values:
            entry[ref_field.leaf_field] = [value for value in values if value != pk]

    elif kind is ExternalRefKind.NESTED_OBJECT:
        nested = entry.get(ref_field.top_level_field)
        if isinstance(nested, dict) and nested.get(ref_field.leaf_field) == pk:
            nested[ref_field.leaf_field] = None

    elif kind is ExternalRefKind.NESTED_LIST:
        for item in entry.get(ref_field.top_level_field) or []:
            if isinstance(item, dict) and item.get(ref_field.leaf_field) == pk:
                item[ref_field.leaf_field] = None

    elif kind is ExternalRefKind.NESTED_SCALAR_LIST:
        nested = entry.get(ref_field.top_level_field)
        if isinstance(nested, dict):
            values = nested.get(ref_field.leaf_field)
            if isinstance(values, list) and pk in values:
                nested[ref_field.leaf_field] = [
                    value for value in values if value != pk
                ]


def _extract_pks(entry: dict, ref_field: ExternalRefField):
    kind = ref_field.kind

    if kind is ExternalRefKind.SCALAR:
        pk = entry.get(ref_field.leaf_field)
        if isinstance(pk, int):
            yield pk

    elif kind is ExternalRefKind.SCALAR_LIST:
        for pk in entry.get(ref_field.leaf_field) or []:
            if isinstance(pk, int):
                yield pk

    elif kind is ExternalRefKind.NESTED_OBJECT:
        nested = entry.get(ref_field.top_level_field)
        if isinstance(nested, dict):
            pk = nested.get(ref_field.leaf_field)
            if isinstance(pk, int):
                yield pk

    elif kind is ExternalRefKind.NESTED_LIST:
        for item in entry.get(ref_field.top_level_field) or []:
            if isinstance(item, dict):
                pk = item.get(ref_field.leaf_field)
                if isinstance(pk, int):
                    yield pk

    elif kind is ExternalRefKind.NESTED_SCALAR_LIST:
        nested = entry.get(ref_field.top_level_field)
        if isinstance(nested, dict):
            for pk in nested.get(ref_field.leaf_field) or []:
                if isinstance(pk, int):
                    yield pk


def _org_scoped_existing_pks(
    target_model: type, pks: set[int], org_lookup: str | None, org_id: int
) -> set[int]:
    queryset = target_model.objects.filter(pk__in=pks)
    if org_lookup is not None:
        queryset = queryset.filter(**{org_lookup: org_id})
    return set(queryset.values_list("pk", flat=True))


def find_dead_external_refs(payload: dict, graph) -> list[DeadRef]:
    """Find every outward ref in *payload* whose target is gone or has moved
    to another org, null it in place, and return a DeadRef per stripped ref.

    Covers both persisted entries (int ``id``) and not-yet-flushed ones
    (``temp_id``): a temp node whose target was deleted between its creation
    and the first flush would otherwise fail validation on every subsequent
    flush and wedge the whole graph's autosave.

    Batches one org-scoped existence query per distinct target model (not per
    node/ref) — a handful of queries regardless of graph size. For any pk that
    fails its org-scoped query, runs one extra unscoped query per target model
    (only when something failed) to classify the reason as ``"deleted"`` vs
    ``"cross_org"`` for logging.
    """
    occurrences: list[tuple[str, int | str, ExternalRefField, int]] = []

    for config in NODE_TYPE_REGISTRY:
        if not config.external_ref_fields:
            continue
        for entry in payload.get(config.list_key) or []:
            if entry is None:
                continue
            node_id = entry.get("id")
            node_key = node_id if isinstance(node_id, int) else entry.get("temp_id")
            if not isinstance(node_key, (int, str)):
                continue
            for ref_field in config.external_ref_fields:
                for pk in _extract_pks(entry, ref_field):
                    occurrences.append((config.list_key, node_key, ref_field, pk))

    if not occurrences:
        return []

    pks_by_model: dict[type, set[int]] = defaultdict(set)
    org_lookup_by_model: dict[type, str | None] = {}
    for _list_key, _node_key, ref_field, pk in occurrences:
        pks_by_model[ref_field.target_model].add(pk)
        org_lookup_by_model[ref_field.target_model] = ref_field.org_lookup

    visible_by_model: dict[type, set[int]] = {
        target_model: _org_scoped_existing_pks(
            target_model, pks, org_lookup_by_model[target_model], graph.org_id
        )
        for target_model, pks in pks_by_model.items()
    }
    unscoped_existing_by_model: dict[type, set[int]] = {}

    dead_refs: list[DeadRef] = []
    for list_key, node_key, ref_field, pk in occurrences:
        target_model = ref_field.target_model
        if pk in visible_by_model[target_model]:
            continue

        if target_model not in unscoped_existing_by_model:
            failed_pks = pks_by_model[target_model] - visible_by_model[target_model]
            unscoped_existing_by_model[target_model] = set(
                target_model.objects.filter(pk__in=failed_pks).values_list(
                    "pk", flat=True
                )
            )
        reason = (
            "cross_org" if pk in unscoped_existing_by_model[target_model] else "deleted"
        )

        id_key = "id" if isinstance(node_key, int) else "temp_id"
        entry = next(
            e
            for e in payload[list_key]
            if e is not None and e.get(id_key) == node_key
        )
        null_ref_in_entry(entry, ref_field, pk)

        dead_ref = DeadRef(
            list_key,
            node_key if isinstance(node_key, int) else None,
            ref_field,
            pk,
            reason,
            None if isinstance(node_key, int) else node_key,
        )
        dead_refs.append(dead_ref)

        if reason == "cross_org":
            logger.warning(
                "find_dead_external_refs: cross-org reference stripped — "
                "graph={}, list_key={}, node={}, field={}, pk={}",
                graph.id,
                list_key,
                node_key,
                dead_ref.field_path,
                pk,
            )
        else:
            logger.info(
                "find_dead_external_refs: deleted reference stripped — "
                "graph={}, list_key={}, node={}, field={}, pk={}",
                graph.id,
                list_key,
                node_key,
                dead_ref.field_path,
                pk,
            )

    return dead_refs
