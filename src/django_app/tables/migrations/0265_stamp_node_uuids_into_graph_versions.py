"""Write each node's uuid into the graph versions saved before nodes had one.

A version snapshot lists its nodes under ``snapshot["nodes"]`` with their ``id`` in
every export format (v1 to v3), so the snapshot is stamped in place and its
``"version"`` key is left as it is. Node ids come from the global sequence
``tables_global_node_seq``, which is older than ``GraphVersion``, so a snapshot node
whose id matches a node row of the same graph is that node.

A node uuid is unique only inside one graph, so the id -> uuid map is built per
graph and never across graphs. Nodes deleted since the version was saved find no
row and stay without a uuid. A uuid a snapshot node already has is never replaced,
so a second run changes nothing.

Historical managers are plain managers, so soft-deleted graphs, versions and node
rows are included. The migration is not atomic: each graph's versions are saved
as they are done, and an interrupted run can simply be run again.
"""

from django.db import migrations

NODE_MODEL_NAMES = (
    "AgentNode",
    "AudioTranscriptionNode",
    "ClassificationDecisionTableNode",
    "DecisionTableNode",
    "EndNode",
    "FileExtractorNode",
    "GraphNote",
    "KeyValueNode",
    "KnowledgeNode",
    "PythonNode",
    "ScheduleTriggerNode",
    "StartNode",
    "SubGraphNode",
    "TaskNode",
    "TelegramTriggerNode",
    "WebhookTriggerNode",
)

# Snapshots can be large, so versions are read and written in small batches.
VERSION_BATCH_SIZE = 50


def _node_uuids_by_id(node_models, graph_id):
    querysets = [
        model._base_manager.filter(graph_id=graph_id).values_list("id", "uuid")
        for model in node_models
    ]
    first, *rest = querysets
    return {node_id: str(uuid) for node_id, uuid in first.union(*rest, all=True)}


def _stamp_snapshot(snapshot, node_uuids_by_id):
    """Add the uuid to each snapshot node that has none; return True if any was added."""
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("nodes"), list):
        return False
    changed = False
    for node in snapshot["nodes"]:
        if not isinstance(node, dict) or node.get("uuid"):
            continue
        node_id = node.get("id")
        if type(node_id) is not int or node_id not in node_uuids_by_id:
            continue
        node["uuid"] = node_uuids_by_id[node_id]
        changed = True
    return changed


def stamp_node_uuids(apps, schema_editor):
    GraphVersion = apps.get_model("tables", "GraphVersion")
    node_models = [apps.get_model("tables", name) for name in NODE_MODEL_NAMES]

    graph_ids = (
        GraphVersion._base_manager.values_list("graph_id", flat=True)
        .distinct()
        .order_by("graph_id")
    )
    for graph_id in graph_ids.iterator():
        node_uuids_by_id = _node_uuids_by_id(node_models, graph_id)
        if not node_uuids_by_id:
            continue
        versions = (
            GraphVersion._base_manager.filter(graph_id=graph_id)
            .only("id", "snapshot")
            .order_by("id")
        )
        changed_versions = []
        for version in versions.iterator(chunk_size=VERSION_BATCH_SIZE):
            if _stamp_snapshot(version.snapshot, node_uuids_by_id):
                changed_versions.append(version)
            if len(changed_versions) == VERSION_BATCH_SIZE:
                GraphVersion._base_manager.bulk_update(changed_versions, ["snapshot"])
                changed_versions = []
        if changed_versions:
            GraphVersion._base_manager.bulk_update(changed_versions, ["snapshot"])


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("tables", "0264_merge_0262_node_uuid_0263_merge_20261009_0941"),
    ]

    operations = [
        migrations.RunPython(stamp_node_uuids, migrations.RunPython.noop),
    ]
