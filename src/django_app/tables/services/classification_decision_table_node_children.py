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

from tables.exceptions import (
    PromptNotFoundError,
    SectionIdConflictError,
    SectionNotFoundError,
)
from tables.models.graph_models import (
    ClassificationConditionGroup,
    ClassificationConditionGroupSection,
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

# Keys never written as-is; `prompt_id`/`section` are resolved node-locally instead.
_GROUP_EXCLUDED_INPUT = {
    "id",
    "classification_decision_table_node",
    "classification_decision_table_node_id",
    "prompt_key",
    "prompt_id",
    "section",
}


def sync_classification_decision_table_children(
    node, *, prompt_configs_data=None, condition_groups_data=None, sections_data=None
):
    """Reconcile a CDT node's prompt configs, sections, and condition groups
    from validated data.

    Prompt configs and sections are synced first so condition groups can
    resolve their ``prompt``/``section`` FKs against the node's current rows.
    ``None`` means "not in this payload — leave untouched"; an empty list
    means "remove all".
    """
    if prompt_configs_data is not None:
        _sync_prompt_configs(node, prompt_configs_data)
    if sections_data is not None:
        sections_by_id = _sync_condition_group_sections(node, sections_data)
    else:
        sections_by_id = {str(s.id): s for s in node.sections.all()}
    if condition_groups_data is not None:
        _sync_condition_groups(node, condition_groups_data, sections_by_id)


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


def _sync_condition_group_sections(node, sections_data):
    """Reconcile a CDT node's condition-group sections (name + metadata).

    Sections use a client-generated UUID as their real PK, so a section
    referenced by a condition group in the same payload can be resolved
    before it's ever been queried from the DB. ``id`` collisions across
    nodes are surfaced as ``SectionIdConflictError`` rather than a raw
    ``IntegrityError``.
    """
    incoming_ids = {s["id"] for s in sections_data}
    node.sections.exclude(id__in=incoming_ids).delete()
    sections_by_id = {}
    for section_data in sections_data:
        existing = ClassificationConditionGroupSection.objects.filter(
            id=section_data["id"]
        ).first()
        if (
            existing is not None
            and existing.classification_decision_table_node_id != node.id
        ):
            raise SectionIdConflictError(section_data["id"])

        section, _ = ClassificationConditionGroupSection.objects.update_or_create(
            id=section_data["id"],
            defaults={
                "classification_decision_table_node": node,
                "name": section_data.get("name", ""),
                "metadata": section_data.get("metadata", {}),
            },
        )
        sections_by_id[str(section.id)] = section
    return sections_by_id


def _resolve_group_section(
    group_data: dict[str, Any],
    sections_by_id: dict[str, ClassificationConditionGroupSection],
) -> ClassificationConditionGroupSection | None:
    """Resolve a condition group's section among this node's sections.

    Returns ``None`` if no section is referenced; raises
    ``SectionNotFoundError`` if a reference is given but not found.
    """
    section_id = group_data.get("section")
    if not section_id:
        return None
    section = sections_by_id.get(str(section_id))
    if section is None:
        raise SectionNotFoundError(section_id)
    return section


def _resolve_group_prompt(
    group_data: dict[str, Any],
    prompt_by_id: dict[int, ClassificationDecisionTablePrompt],
    prompt_by_key: dict[str, ClassificationDecisionTablePrompt],
) -> ClassificationDecisionTablePrompt | None:
    """Resolve a condition group's prompt among this node's prompts.

    Checks ``prompt_id`` first, falling back to ``prompt_key`` (needed to
    link a prompt created in the same payload). Raises
    ``PromptNotFoundError`` if a reference is given but not found; returns
    ``None`` if neither is given.
    """
    prompt_id = group_data.get("prompt_id")
    if prompt_id is not None:
        prompt = prompt_by_id.get(prompt_id)
        if prompt is None:
            raise PromptNotFoundError(prompt_id)
        return prompt

    key = group_data.get("prompt_key")
    if key:
        prompt = prompt_by_key.get(key)
        if prompt is None:
            raise PromptNotFoundError(key)
        return prompt

    return None


def _sync_condition_groups(node, condition_groups_data, sections_by_id):
    graph = node.graph
    node_prompts = list(ClassificationDecisionTablePrompt.objects.filter(cdt_node=node))
    prompt_by_id = {p.id: p for p in node_prompts}
    prompt_by_key = {p.prompt_key: p for p in node_prompts}

    # Normalize payload rows once: strip non-column keys, resolve prompt/section FKs.
    rows = []
    for group_data in condition_groups_data:
        gd = {k: v for k, v in group_data.items() if k not in _GROUP_EXCLUDED_INPUT}
        assert_node_ref_in_graph(
            node_id=gd.get("next_node_id"),
            graph=graph,
            field="condition_groups.next_node_id",
        )
        gd["prompt"] = _resolve_group_prompt(group_data, prompt_by_id, prompt_by_key)
        gd["section"] = _resolve_group_section(group_data, sections_by_id)
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
