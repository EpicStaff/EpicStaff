from django.db import transaction
from rest_framework.exceptions import PermissionDenied

from tables.models import (
    Agent,
    ClassificationDecisionTablePrompt,
    Crew,
    LLMConfig,
)
from tables.models.flow_assistant_models import FlowAssistant
from tables.models.graph_models import ClassificationDecisionTableNode
from tables.models.knowledge_models.graphrag_models import GraphRag
from tables.models.rbac_models.rbac_enums import Permission, ResourceType

IN_USE_RESTRICTED = "in_use_restricted"
SAMPLE_LIMIT = 5


def _agents_items(config_ids, org_id):
    """AGENTS bucket: old Agent.llm_config/fcm_llm_config (tables app) +
    agents.AgentDefinition.llm_config/fcm_llm_config -- same resource_type
    (AGENTS) for both, merged into one bucket."""
    from agents.models import AgentDefinition

    items = {}
    for field in ("llm_config_id", "fcm_llm_config_id"):
        for config_id, item_id, item_name in Agent.objects.filter(
            org_id=org_id, **{f"{field}__in": config_ids}
        ).values_list(field, "id", "role"):
            items.setdefault(config_id, []).append({"id": item_id, "name": item_name})
        for config_id, item_id, item_name in AgentDefinition.objects.filter(
            organization_id=org_id, **{f"{field}__in": config_ids}
        ).values_list(field, "id", "name"):
            items.setdefault(config_id, []).append({"id": item_id, "name": item_name})
    return items


def _projects_items(config_ids, org_id):
    """PROJECTS bucket: Crew.manager_llm_config/memory_llm_config/
    planning_llm_config -- three FK paths, one merged bucket (sample is the
    Crew itself, which is the referencing top-level entity)."""
    items = {}
    for field in (
        "manager_llm_config_id",
        "memory_llm_config_id",
        "planning_llm_config_id",
    ):
        for config_id, item_id, item_name in Crew.objects.filter(
            org_id=org_id, **{f"{field}__in": config_ids}
        ).values_list(field, "id", "name"):
            items.setdefault(config_id, []).append({"id": item_id, "name": item_name})
    return items


def _flows_items(config_ids, org_id):
    """FLOWS bucket: ClassificationDecisionTableNode.default_llm_config,
    ClassificationDecisionTablePrompt.llm_config, and FlowAssistant.llm_config
    -- three sources, one merged bucket. Sample shows the containing Flow
    (Graph), not the individual node/prompt/assistant row, matching the
    "which Flow" convention from Iterations 1/2.

    Note: `CodeAgentNode` was removed from the codebase by the `main` merge
    (superseded by `AgentNode`/`TaskNode`, which reference `agents.
    AgentDefinition` rather than `LLMConfig` directly) -- it used to be a
    fourth source here. No coverage gap: any LLM config an AgentNode/TaskNode
    actually uses reaches this config via `AgentDefinition.llm_config`/
    `fcm_llm_config`, already covered by the AGENTS bucket in `get_usage`.
    """
    items = {}

    for config_id, graph_id, graph_name in (
        ClassificationDecisionTableNode.objects.filter(
            graph__org_id=org_id, default_llm_config_id__in=config_ids
        )
        .values_list("default_llm_config_id", "graph_id", "graph__name")
        .distinct()
    ):
        items.setdefault(config_id, []).append({"id": graph_id, "name": graph_name})

    for config_id, graph_id, graph_name in (
        ClassificationDecisionTablePrompt.objects.filter(
            cdt_node__graph__org_id=org_id, llm_config_id__in=config_ids
        )
        .values_list("llm_config_id", "cdt_node__graph_id", "cdt_node__graph__name")
        .distinct()
    ):
        items.setdefault(config_id, []).append({"id": graph_id, "name": graph_name})

    for config_id, graph_id, graph_name in (
        FlowAssistant.objects.filter(graph__org_id=org_id, llm_config_id__in=config_ids)
        .values_list("llm_config_id", "graph_id", "graph__name")
        .distinct()
    ):
        items.setdefault(config_id, []).append({"id": graph_id, "name": graph_name})

    return items


def _knowledge_sources_items(config_ids, org_id):
    """KNOWLEDGE_SOURCES bucket: GraphRag.llm -- sample shows the containing
    SourceCollection (the recognizable, permission-relevant unit), not the
    internal GraphRag row."""
    items = {}
    rows = (
        GraphRag.objects.filter(
            base_rag_type__source_collection__org_id=org_id, llm_id__in=config_ids
        )
        .values_list(
            "llm_id",
            "base_rag_type__source_collection__collection_id",
            "base_rag_type__source_collection__collection_name",
        )
        .distinct()
    )
    for config_id, item_id, item_name in rows:
        items.setdefault(config_id, []).append({"id": item_id, "name": item_name})
    return items


def get_usage(config_ids, org_id, effective):
    """{config_id: {blocked, by_resource_type: [...]}} across the four
    referencing buckets for LLMConfig. See graph_delete_service.py/
    crew_delete_service.py for the shared shape/visibility rationale
    (one-hop, visible-only, org-wide all-or-nothing until instance-level ACL
    lands). `TemplateAgent.*` and the global `DefaultModels`/
    `DefaultCrewConfig`/`DefaultAgentConfig` singleton fields are
    deliberately excluded -- no independent ViewSet/resource_type to check
    visibility against.
    """
    if not config_ids:
        return {}

    buckets = [
        (ResourceType.AGENTS, _agents_items(config_ids, org_id)),
        (ResourceType.PROJECTS, _projects_items(config_ids, org_id)),
        (ResourceType.FLOWS, _flows_items(config_ids, org_id)),
        (ResourceType.KNOWLEDGE_SOURCES, _knowledge_sources_items(config_ids, org_id)),
    ]

    usage = {}
    for config_id in config_ids:
        by_resource_type = []
        blocked = False
        for resource_type, items_by_config in buckets:
            items = items_by_config.get(config_id, [])
            total_count = len(items)
            can_read = effective.can(resource_type, Permission.READ)
            visible_items = items if can_read else []
            visible_count = len(visible_items)
            if total_count > visible_count:
                blocked = True
            by_resource_type.append(
                {
                    "resource_type": resource_type,
                    "visible_count": visible_count,
                    "visible_sample": visible_items[:SAMPLE_LIMIT],
                    "truncated": visible_count > SAMPLE_LIMIT,
                }
            )
        usage[config_id] = {"blocked": blocked, "by_resource_type": by_resource_type}
    return usage


def assert_llm_config_deletable(config, org_id, effective):
    """Guard for single-object destroy -- mirrors the bulk-delete check so
    both paths enforce the same rule (a user can't bypass the block by
    deleting one-by-one)."""
    if get_usage([config.id], org_id, effective)[config.id]["blocked"]:
        raise PermissionDenied(IN_USE_RESTRICTED)


def bulk_delete_llm_configs(ids, org_id, effective, dry_run=False):
    found = list(LLMConfig.objects.filter(org_id=org_id, id__in=ids))
    found_ids = {config.id for config in found}
    not_found_ids = [i for i in ids if i not in found_ids]

    usage = get_usage(list(found_ids), org_id, effective)

    deleted_ids = []
    skipped_ids = []
    with transaction.atomic():
        for config in found:
            config_id = config.id  # capture before delete() nulls instance.pk
            if usage[config_id]["blocked"]:
                skipped_ids.append({"id": config_id, "reason": IN_USE_RESTRICTED})
                continue
            if not dry_run:
                config.delete()
            deleted_ids.append(config_id)

    return {
        "dry_run": dry_run,
        "deleted_count": len(deleted_ids),
        "deleted_ids": deleted_ids,
        "not_found_ids": not_found_ids,
        "skipped_ids": skipped_ids,
        "usage": {str(config_id): entry for config_id, entry in usage.items()},
    }
