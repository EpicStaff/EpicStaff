"""Shared sync logic for a Classification Decision Table node's children
(prompt configs + condition groups).

Single source of truth called from both the API serializer
(``ClassificationDecisionTableNodeSerializer``) and the single-node service
(``ClassificationDecisionTableNodeService``) so the two paths can't drift.

Keying rules:
- prompt configs   -> ``prompt_key`` (stable, unique per node)
- route-coded groups -> ``(node, route_code)`` (DB-enforced unique)
- route-code-less groups -> matched positionally by ``order``. They have no
  DB-unique key (the model only enforces uniqueness on ``(node, route_code)``),
  and the client sends a full ordered snapshot with no ids, so matching on
  ``group_name`` is unsafe: duplicate names are a normal user state and would
  otherwise raise ``MultipleObjectsReturned`` or silently collapse rows.
"""

from typing import Any

from rest_framework import serializers

from tables.models.graph_models import (
    ClassificationConditionGroup,
    ClassificationDecisionTablePrompt,
)
from tables.serializers.utils.mixins import assert_node_ref_in_graph

# Fields bulk_update is allowed to write back on an existing condition group.
_GROUP_UPDATE_FIELDS = [
    "group_name",
    "order",
    "expression",
    "prompt",
    "manipulation",
    "continue_flag",
    "next_node_id",
    "dock_visible",
    "field_expressions",
    "field_manipulations",
    "section",
]

# Validated keys that must not be written to the group as-is. `prompt_id` is
# stripped here and re-added only as a node-local instance via `_resolve_prompt`,
# so a foreign prompt can't attach directly. The rest guard against a raw
# non-column key ever forcing a PK or colliding with the explicit node kwarg.
_GROUP_EXCLUDED_INPUT = {
    "id",
    "classification_decision_table_node",
    "classification_decision_table_node_id",
    "prompt_key",
    "prompt_id",
}


def sync_classification_decision_table_children(
    node, *, prompt_configs_data=None, condition_groups_data=None
):
    """Reconcile a CDT node's prompt configs and condition groups from validated data.

    Prompt configs are synced first so condition groups can resolve their
    ``prompt`` FK against the node's current prompts. ``None`` means "not in
    this payload — leave untouched"; an empty list means "remove all".
    """
    if prompt_configs_data is not None:
        _sync_prompt_configs(node, prompt_configs_data)
    if condition_groups_data is not None:
        _sync_condition_groups(node, condition_groups_data)


def _sync_prompt_configs(node, prompt_configs_data):
    incoming_keys = {pd["prompt_key"] for pd in prompt_configs_data}
    ClassificationDecisionTablePrompt.objects.filter(cdt_node=node).exclude(
        prompt_key__in=incoming_keys
    ).delete()
    for prompt_data in prompt_configs_data:
        defaults = {k: v for k, v in prompt_data.items() if k != "prompt_key"}
        ClassificationDecisionTablePrompt.objects.update_or_create(
            cdt_node=node,
            prompt_key=prompt_data["prompt_key"],
            defaults=defaults,
        )


def _prompt_not_found_error(
    field: str, value: int | str
) -> serializers.ValidationError:
    """A prompt reference that doesn't resolve to one of THIS node's prompts —
    whether it belongs to another org/node or doesn't exist at all is
    indistinguishable from here, so both cases share the same message (no
    existence leak)."""
    return serializers.ValidationError(
        {field: f"Prompt {value} is not found or belong to another organization."}
    )


def _resolve_group_prompt(
    group_data: dict[str, Any],
    prompt_by_id: dict[int, ClassificationDecisionTablePrompt],
    prompt_by_key: dict[str, ClassificationDecisionTablePrompt],
) -> ClassificationDecisionTablePrompt | None:
    """Resolve a condition group's prompt to one of THIS node's prompts.

    ``prompt_id`` (an already-persisted prompt) is checked first when present.
    Only when it is absent do we fall back to ``prompt_key`` — the prompt's
    stable per-node key, known even for a prompt created in this same payload,
    which is what lets create+connect work in a single save.

    Both maps are built from THIS node's prompts only, so a reference that
    names a prompt belonging to another node/org is indistinguishable from one
    that doesn't exist at all — either way the lookup misses and we raise,
    rather than silently dropping the link. A group with neither reference
    supplied simply has no prompt (returns ``None``, not an error).
    """
    prompt_id = group_data.get("prompt_id")
    if prompt_id is not None:
        prompt = prompt_by_id.get(prompt_id)
        if prompt is None:
            raise _prompt_not_found_error(
                field="condition_groups.prompt", value=prompt_id
            )
        return prompt

    key = group_data.get("prompt_key")
    if key:
        prompt = prompt_by_key.get(key)
        if prompt is None:
            raise _prompt_not_found_error(
                field="condition_groups.prompt_key", value=key
            )
        return prompt

    return None


def _sync_condition_groups(node, condition_groups_data):
    graph = node.graph
    node_prompts = list(ClassificationDecisionTablePrompt.objects.filter(cdt_node=node))
    prompt_by_id = {p.id: p for p in node_prompts}
    prompt_by_key = {p.prompt_key: p for p in node_prompts}

    # Normalize payload rows once: strip non-column keys, resolve prompt FK.
    rows = []
    for group_data in condition_groups_data:
        gd = {k: v for k, v in group_data.items() if k not in _GROUP_EXCLUDED_INPUT}
        assert_node_ref_in_graph(
            node_id=gd.get("next_node_id"),
            graph=graph,
            field="condition_groups.next_node_id",
        )
        gd["prompt"] = _resolve_group_prompt(group_data, prompt_by_id, prompt_by_key)
        rows.append(gd)

    routed = [gd for gd in rows if gd.get("route_code")]
    unrouted = [gd for gd in rows if not gd.get("route_code")]

    to_update = []
    to_create = []

    # --- route-coded groups: upsert on the unique (node, route_code) ---
    incoming_route_codes = {gd["route_code"] for gd in routed}
    node.condition_groups.exclude(route_code__isnull=True).exclude(
        route_code__in=incoming_route_codes
    ).delete()
    existing_by_rc = {
        g.route_code: g for g in node.condition_groups.exclude(route_code__isnull=True)
    }
    for gd in routed:
        existing = existing_by_rc.get(gd["route_code"])
        if existing is not None:
            for attr, val in gd.items():
                setattr(existing, attr, val)
            to_update.append(existing)
        else:
            to_create.append(
                ClassificationConditionGroup(
                    classification_decision_table_node=node, **gd
                )
            )

    # --- route-code-less groups: no unique key, match positionally by order ---
    existing_unrouted = list(
        node.condition_groups.filter(route_code__isnull=True).order_by("order", "id")
    )
    unrouted.sort(key=lambda gd: gd.get("order") or 0)
    for index, gd in enumerate(unrouted):
        if index < len(existing_unrouted):
            existing = existing_unrouted[index]
            for attr, val in gd.items():
                setattr(existing, attr, val)
            to_update.append(existing)
        else:
            to_create.append(
                ClassificationConditionGroup(
                    classification_decision_table_node=node, **gd
                )
            )
    surplus_ids = [g.id for g in existing_unrouted[len(unrouted) :]]

    if surplus_ids:
        ClassificationConditionGroup.objects.filter(id__in=surplus_ids).delete()
    if to_update:
        ClassificationConditionGroup.objects.bulk_update(
            to_update, _GROUP_UPDATE_FIELDS
        )
    if to_create:
        ClassificationConditionGroup.objects.bulk_create(to_create)
