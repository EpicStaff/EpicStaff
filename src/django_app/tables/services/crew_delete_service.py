from django.db import transaction
from rest_framework.exceptions import PermissionDenied

from tables.models import Crew, CrewNode, Task
from tables.models.rbac_models.rbac_enums import Permission, ResourceType

IN_USE_RESTRICTED = "in_use_restricted"
SAMPLE_LIMIT = 5


def _usage_source(crew_ids, items_by_crew, can_read, resource_type):
    """{crew_id: (source_dict, total_count)} for one referencing source --
    source_dict is the public {resource_type, visible_count, visible_sample,
    truncated} shape; total_count is kept alongside (not in the public dict)
    so the caller can compute `blocked` without leaking it."""
    result = {}
    for crew_id in crew_ids:
        items = items_by_crew.get(crew_id, [])
        total_count = len(items)
        visible_items = items if can_read else []
        visible_count = len(visible_items)
        source = {
            "resource_type": resource_type,
            "visible_count": visible_count,
            "visible_sample": visible_items[:SAMPLE_LIMIT],
            "truncated": visible_count > SAMPLE_LIMIT,
        }
        result[crew_id] = (source, total_count)
    return result


def _crew_node_usage(crew_ids, org_id, effective):
    """Distinct parent Flows (Graph id/name) embedding each crew via
    CrewNode.crew -- resource_type FLOWS."""
    rows = (
        CrewNode.objects.filter(crew_id__in=crew_ids, graph__org_id=org_id)
        .values("crew_id", "graph_id", "graph__name")
        .distinct()
    )
    parents_by_crew = {}
    for row in rows:
        parents_by_crew.setdefault(row["crew_id"], []).append(
            {"id": row["graph_id"], "name": row["graph__name"]}
        )
    can_read_flows = effective.can(ResourceType.FLOWS, Permission.READ)
    return _usage_source(crew_ids, parents_by_crew, can_read_flows, ResourceType.FLOWS)


def _task_usage(crew_ids, org_id, effective):
    """Distinct Tasks referencing each crew via Task.crew -- resource_type
    PROJECTS (same bucket as Crew itself today, but checked the same way for
    consistency and to stay correct once instance-level ACL differentiates
    visibility within PROJECTS)."""
    rows = (
        Task.objects.filter(crew_id__in=crew_ids, crew__org_id=org_id)
        .values("crew_id", "id", "name")
        .distinct()
    )
    tasks_by_crew = {}
    for row in rows:
        tasks_by_crew.setdefault(row["crew_id"], []).append(
            {"id": row["id"], "name": row["name"]}
        )
    can_read_projects = effective.can(ResourceType.PROJECTS, Permission.READ)
    return _usage_source(
        crew_ids, tasks_by_crew, can_read_projects, ResourceType.PROJECTS
    )


def get_usage(crew_ids, org_id, effective):
    """{crew_id: {blocked, by_resource_type: [...]}} combining the FLOWS
    (CrewNode) and PROJECTS (Task) sources -- see graph_delete_service.py
    for the shared shape/visibility rationale. `blocked` is true if either
    source has a hidden (total > visible) portion.

    Note: `UserSessionMessage.crew`/`AgentSessionMessage.crew`/
    `TaskSessionMessage.crew` (all SET_NULL) are deliberately NOT checked
    here -- they have no independent ViewSet/resource_type of their own to
    check visibility against, so there's no permission boundary to enforce;
    they behave exactly as they do today (SET_NULL on delete).
    """
    if not crew_ids:
        return {}

    flows_by_crew = _crew_node_usage(crew_ids, org_id, effective)
    projects_by_crew = _task_usage(crew_ids, org_id, effective)

    usage = {}
    for crew_id in crew_ids:
        flows_source, flows_total = flows_by_crew[crew_id]
        projects_source, projects_total = projects_by_crew[crew_id]
        usage[crew_id] = {
            "blocked": (
                flows_total > flows_source["visible_count"]
                or projects_total > projects_source["visible_count"]
            ),
            "by_resource_type": [flows_source, projects_source],
        }
    return usage


def assert_crew_deletable(crew, org_id, effective):
    """Guard for single-object destroy -- mirrors the bulk-delete check so
    both paths enforce the same rule (a user can't bypass the block by
    deleting one-by-one)."""
    if get_usage([crew.id], org_id, effective)[crew.id]["blocked"]:
        raise PermissionDenied(IN_USE_RESTRICTED)


def bulk_delete_crews(ids, org_id, effective, dry_run=False):
    found = list(Crew.objects.filter(org_id=org_id, id__in=ids))
    found_ids = {crew.id for crew in found}
    not_found_ids = [i for i in ids if i not in found_ids]

    usage = get_usage(list(found_ids), org_id, effective)

    deleted_ids = []
    skipped_ids = []
    with transaction.atomic():
        for crew in found:
            crew_id = crew.id  # capture before delete() nulls instance.pk
            if usage[crew_id]["blocked"]:
                skipped_ids.append({"id": crew_id, "reason": IN_USE_RESTRICTED})
                continue
            if not dry_run:
                crew.delete()
            deleted_ids.append(crew_id)

    return {
        "dry_run": dry_run,
        "deleted_count": len(deleted_ids),
        "deleted_ids": deleted_ids,
        "not_found_ids": not_found_ids,
        "skipped_ids": skipped_ids,
        "usage": {str(crew_id): entry for crew_id, entry in usage.items()},
    }
