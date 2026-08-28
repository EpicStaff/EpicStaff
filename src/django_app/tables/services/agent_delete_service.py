from django.db import transaction
from rest_framework.exceptions import PermissionDenied

from tables.models import Agent, Crew, Task
from tables.models.rbac_models.rbac_enums import Permission, ResourceType

IN_USE_RESTRICTED = "in_use_restricted"
SAMPLE_LIMIT = 5


def _crew_agent_usage(agent_ids, org_id):
    """Distinct Crews referencing each agent via the Crew.agents M2M."""
    rows = (
        Crew.agents.through.objects.filter(agent_id__in=agent_ids, crew__org_id=org_id)
        .values("agent_id", "crew_id", "crew__name")
        .distinct()
    )
    items_by_agent = {}
    for row in rows:
        items_by_agent.setdefault(row["agent_id"], []).append(
            {"id": row["crew_id"], "name": row["crew__name"]}
        )
    return items_by_agent


def _task_agent_usage(agent_ids, org_id):
    """Distinct Tasks referencing each agent via Task.agent. Org-scoped
    through the task's crew, matching TaskReadWriteViewSet.org_filter_path =
    "crew__org_id" -- a task with no crew is therefore excluded here too,
    same as it would be from that ViewSet's own queryset."""
    rows = (
        Task.objects.filter(agent_id__in=agent_ids, crew__org_id=org_id)
        .values("agent_id", "id", "name")
        .distinct()
    )
    items_by_agent = {}
    for row in rows:
        items_by_agent.setdefault(row["agent_id"], []).append(
            {"id": row["id"], "name": row["name"]}
        )
    return items_by_agent


def get_usage(agent_ids, org_id, effective):
    """{agent_id: {blocked, by_resource_type: [...]}} -- Agent's two
    referencing sources (Crew.agents M2M, Task.agent FK) both live under
    resource_type PROJECTS, so they're merged into ONE combined entry
    (single visibility check, one merged sample) rather than two
    same-labeled entries -- see graph_delete_service.py/crew_delete_service.py
    for the shared shape/visibility rationale (one-hop, visible-only,
    org-wide all-or-nothing until instance-level ACL lands).

    RealtimeAgent (1:1 CASCADE component of Agent) and the deprecated
    Agent*Tools through-tables / AgentSessionMessage.agent are deliberately
    NOT checked here -- see agent iteration notes in the plan for why.
    """
    if not agent_ids:
        return {}

    crew_items = _crew_agent_usage(agent_ids, org_id)
    task_items = _task_agent_usage(agent_ids, org_id)
    can_read_projects = effective.can(ResourceType.PROJECTS, Permission.READ)

    usage = {}
    for agent_id in agent_ids:
        items = crew_items.get(agent_id, []) + task_items.get(agent_id, [])
        total_count = len(items)
        visible_items = items if can_read_projects else []
        visible_count = len(visible_items)
        usage[agent_id] = {
            "blocked": total_count > visible_count,
            "by_resource_type": [
                {
                    "resource_type": ResourceType.PROJECTS,
                    "visible_count": visible_count,
                    "visible_sample": visible_items[:SAMPLE_LIMIT],
                    "truncated": visible_count > SAMPLE_LIMIT,
                }
            ],
        }
    return usage


def assert_agent_deletable(agent, org_id, effective):
    """Guard for single-object destroy -- mirrors the bulk-delete check so
    both paths enforce the same rule (a user can't bypass the block by
    deleting one-by-one)."""
    if get_usage([agent.id], org_id, effective)[agent.id]["blocked"]:
        raise PermissionDenied(IN_USE_RESTRICTED)


def bulk_delete_agents(ids, org_id, effective, dry_run=False):
    found = list(Agent.objects.filter(org_id=org_id, id__in=ids))
    found_ids = {agent.id for agent in found}
    not_found_ids = [i for i in ids if i not in found_ids]

    usage = get_usage(list(found_ids), org_id, effective)

    deleted_ids = []
    skipped_ids = []
    with transaction.atomic():
        for agent in found:
            agent_id = agent.id  # capture before delete() nulls instance.pk
            if usage[agent_id]["blocked"]:
                skipped_ids.append({"id": agent_id, "reason": IN_USE_RESTRICTED})
                continue
            if not dry_run:
                agent.delete()
            deleted_ids.append(agent_id)

    return {
        "dry_run": dry_run,
        "deleted_count": len(deleted_ids),
        "deleted_ids": deleted_ids,
        "not_found_ids": not_found_ids,
        "skipped_ids": skipped_ids,
        "usage": {str(agent_id): entry for agent_id, entry in usage.items()},
    }
