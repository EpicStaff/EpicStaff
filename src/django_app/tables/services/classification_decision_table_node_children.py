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

from tables.models.graph_models import (
    ClassificationConditionGroup,
    ClassificationDecisionTablePrompt,
)

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

# Incoming keys that are not writable group columns.
_GROUP_EXCLUDED_INPUT = {"id", "classification_decision_table_node", "prompt_key"}


def sync_classification_decision_table_children(
    node, *, prompt_configs_data=None, condition_groups_data=None
):
    """Sync a CDT node's prompt configs and condition groups from payload data.

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
        defaults = {
            k: v
            for k, v in prompt_data.items()
            if k not in ("prompt_key", "id", "cdt_node")
        }
        ClassificationDecisionTablePrompt.objects.update_or_create(
            cdt_node=node,
            prompt_key=prompt_data["prompt_key"],
            defaults=defaults,
        )


def _resolve_prompt(value, prompt_by_id):
    """Normalize an incoming ``prompt`` reference to one of the node's prompts.

    Callers pass either a raw int id (service/frontend payload) or an already
    resolved ``ClassificationDecisionTablePrompt`` instance (the serializer's
    ``PrimaryKeyRelatedField``). Both collapse to the node-local prompt, or
    ``None`` if it doesn't belong to this node.
    """
    if value is None:
        return None
    if isinstance(value, ClassificationDecisionTablePrompt):
        return prompt_by_id.get(value.id)
    return prompt_by_id.get(value)


def _sync_condition_groups(node, condition_groups_data):
    prompt_by_id = {
        p.id: p
        for p in ClassificationDecisionTablePrompt.objects.filter(cdt_node=node)
    }

    # Normalize payload rows once: strip non-column keys, resolve prompt FK.
    rows = []
    for group_data in condition_groups_data:
        gd = {k: v for k, v in group_data.items() if k not in _GROUP_EXCLUDED_INPUT}
        gd["prompt"] = _resolve_prompt(gd.pop("prompt", None), prompt_by_id)
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
        g.route_code: g
        for g in node.condition_groups.exclude(route_code__isnull=True)
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
    surplus_ids = [g.id for g in existing_unrouted[len(unrouted):]]

    if surplus_ids:
        ClassificationConditionGroup.objects.filter(id__in=surplus_ids).delete()
    if to_update:
        ClassificationConditionGroup.objects.bulk_update(
            to_update, _GROUP_UPDATE_FIELDS
        )
    if to_create:
        ClassificationConditionGroup.objects.bulk_create(to_create)
