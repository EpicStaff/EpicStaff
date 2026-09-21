from django.db import transaction
from rest_framework.exceptions import PermissionDenied

from tables.models import Graph, SubGraphNode
from tables.models.rbac_models.rbac_enums import Permission, ResourceType

IN_USE_RESTRICTED = "in_use_restricted"
SAMPLE_LIMIT = 5


def get_usage(graph_ids, org_id, effective):
    """{graph_id: {blocked, by_resource_type: [{resource_type, visible_count,
    visible_sample, truncated}]}} for every id in graph_ids, describing how
    each is embedded as a subgraph elsewhere (SubGraphNode.subgraph), scoped
    to the active org. `by_resource_type` has exactly one entry today (only
    one referencing source exists for Graph) -- the array shape matches
    every other entity's `get_usage` (e.g. Crew, which genuinely has more
    than one source) for one consistent contract across the API.

    "visible" is currently all-or-nothing per org (FLOWS:READ present -> see
    every parent Flow referencing this graph; absent -> see none) since
    there is no instance-level ACL yet -- this is the one place to add a
    per-row filter when that lands. `blocked` is true whenever there's any
    parent Flow beyond what's visible; `visible_count`/`visible_sample`
    never include anything about that hidden portion (no count, no ids).
    """
    if not graph_ids:
        return {}

    rows = (
        SubGraphNode.objects.filter(subgraph_id__in=graph_ids, graph__org_id=org_id)
        .values("subgraph_id", "graph_id", "graph__name")
        .distinct()
    )

    parents_by_subgraph = {}
    for row in rows:
        parents_by_subgraph.setdefault(row["subgraph_id"], []).append(
            {"id": row["graph_id"], "name": row["graph__name"]}
        )

    can_read_flows = effective.can(ResourceType.FLOWS, Permission.READ)

    usage = {}
    for graph_id in graph_ids:
        parents = parents_by_subgraph.get(graph_id, [])
        total_count = len(parents)
        visible_parents = parents if can_read_flows else []
        visible_count = len(visible_parents)
        usage[graph_id] = {
            "blocked": total_count > visible_count,
            "by_resource_type": [
                {
                    "resource_type": ResourceType.FLOWS,
                    "visible_count": visible_count,
                    "visible_sample": visible_parents[:SAMPLE_LIMIT],
                    "truncated": visible_count > SAMPLE_LIMIT,
                }
            ],
        }
    return usage


def assert_graph_deletable(graph, org_id, effective):
    """Guard for single-object destroy -- mirrors the bulk-delete check so
    both paths enforce the same rule (a user can't bypass the block by
    deleting one-by-one)."""
    if get_usage([graph.id], org_id, effective)[graph.id]["blocked"]:
        raise PermissionDenied(IN_USE_RESTRICTED)


def bulk_delete_graphs(ids, org_id, effective, dry_run=False):
    found = list(Graph.objects.filter(org_id=org_id, id__in=ids))
    found_ids = {graph.id for graph in found}
    not_found_ids = [i for i in ids if i not in found_ids]

    usage = get_usage(list(found_ids), org_id, effective)

    deleted_ids = []
    skipped_ids = []
    with transaction.atomic():
        for graph in found:
            graph_id = graph.id  # capture before delete() nulls instance.pk
            if usage[graph_id]["blocked"]:
                skipped_ids.append({"id": graph_id, "reason": IN_USE_RESTRICTED})
                continue
            if not dry_run:
                graph.delete()
            deleted_ids.append(graph_id)

    return {
        "dry_run": dry_run,
        "deleted_count": len(deleted_ids),
        "deleted_ids": deleted_ids,
        "not_found_ids": not_found_ids,
        "skipped_ids": skipped_ids,
        "usage": {str(graph_id): entry for graph_id, entry in usage.items()},
    }
