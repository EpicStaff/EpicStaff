"""Move each node's "#N" badge into node_number.

Until now the badge lived twice: as a " #N" suffix of node_name and as
metadata["nodeNumber"]. For every numbered node this migration picks the badge
number, strips a matching suffix from the name, removes metadata["nodeNumber"],
and seeds Graph.node_number_seq with the highest number in the graph. Version
snapshots get the same rewrite, so each stored snapshot holds a single source of
truth for the badge too (preview and restore still run it through the converter).

The rule is copied here rather than imported: a migration must keep doing what it
did when it was written, whatever the app code turns into later.
"""

import re

from django.db import migrations

NUMBERED_NODE_MODELS = (
    "CrewNode",
    "PythonNode",
    "KnowledgeNode",
    "FileExtractorNode",
    "KeyValueNode",
    "AudioTranscriptionNode",
    "SubGraphNode",
    "TaskNode",
    "AgentNode",
    "DecisionTableNode",
    "ClassificationDecisionTableNode",
    "WebhookTriggerNode",
    "TelegramTriggerNode",
    "ScheduleTriggerNode",
)

# The export "node_type" of each model above; SubGraphNode exports as "SubgraphNode".
# CrewNode is absent: it is never exported, so no snapshot holds one.
NUMBERED_SNAPSHOT_NODE_TYPES = frozenset(
    {
        "PythonNode",
        "KnowledgeNode",
        "FileExtractorNode",
        "KeyValueNode",
        "AudioTranscriptionNode",
        "SubgraphNode",
        "TaskNode",
        "AgentNode",
        "DecisionTableNode",
        "ClassificationDecisionTableNode",
        "WebhookTriggerNode",
        "TelegramTriggerNode",
        "ScheduleTriggerNode",
    }
)

NODE_NUMBER_METADATA_KEY = "nodeNumber"
NAME_BADGE_SUFFIX = re.compile(r"\s*#\s*(\d+)\s*$")
GRAPH_CHUNK_SIZE = 500
# A snapshot is a whole graph export: keep few in memory and in one UPDATE.
SNAPSHOT_BATCH_SIZE = 25
# Far above any real badge, and keeps node_number_seq + 1 far from int32 overflow.
MAX_BADGE_NUMBER = 1_000_000


def _is_badge_number(number):
    # Exact type match: bool is a subclass of int and is not a badge number.
    return type(number) is int and 1 <= number <= MAX_BADGE_NUMBER


def _metadata_number(metadata):
    if not isinstance(metadata, dict):
        return None
    number = metadata.get(NODE_NUMBER_METADATA_KEY)
    return number if _is_badge_number(number) else None


def _name_suffix_number(node_name):
    match = NAME_BADGE_SUFFIX.search(node_name or "")
    return int(match.group(1)) if match else None


def _clean_name(node_name, candidate):
    """Drop the " #N" suffix when it is the node's own badge and a label remains."""
    if candidate is None or _name_suffix_number(node_name) != candidate:
        return node_name
    label = NAME_BADGE_SUFFIX.sub("", node_name)
    return label if label.strip() else node_name


def _without_number_key(metadata):
    if not isinstance(metadata, dict) or NODE_NUMBER_METADATA_KEY not in metadata:
        return metadata
    return {key: value for key, value in metadata.items() if key != NODE_NUMBER_METADATA_KEY}


def _split_badges(nodes):
    """Compute the badge of each node of one graph.

    Args:
        nodes: ``(sort_key, node_name, metadata)`` tuples; ``sort_key`` orders the
            nodes the way their ids do.

    Returns:
        ``(node_name, node_number, metadata)`` per input node, in input order, and
        the highest number assigned (0 when there are no nodes).
    """
    candidates = []
    for _sort_key, node_name, metadata in nodes:
        candidate = _metadata_number(metadata)
        if candidate is None:
            suffix_number = _name_suffix_number(node_name)
            if _is_badge_number(suffix_number):
                candidate = suffix_number
        candidates.append(candidate)

    numbers = [None] * len(nodes)
    taken = set()
    for index in sorted(range(len(nodes)), key=lambda position: nodes[position][0]):
        candidate = candidates[index]
        if candidate is not None and candidate not in taken:
            numbers[index] = candidate
            taken.add(candidate)

    highest = max(taken, default=0)
    for index in sorted(range(len(nodes)), key=lambda position: nodes[position][0]):
        if numbers[index] is None:
            highest += 1
            numbers[index] = highest

    results = [
        (_clean_name(node_name, candidates[index]), numbers[index], _without_number_key(metadata))
        for index, (_sort_key, node_name, metadata) in enumerate(nodes)
    ]
    return results, highest


def _backfill_live_nodes(apps):
    graph_model = apps.get_model("tables", "Graph")
    node_models = [apps.get_model("tables", name) for name in NUMBERED_NODE_MODELS]

    graph_ids = graph_model._base_manager.order_by("id").values_list("id", flat=True)
    chunk = []
    for graph_id in graph_ids.iterator(chunk_size=GRAPH_CHUNK_SIZE):
        chunk.append(graph_id)
        if len(chunk) == GRAPH_CHUNK_SIZE:
            _backfill_graph_chunk(graph_model, node_models, chunk)
            chunk = []
    if chunk:
        _backfill_graph_chunk(graph_model, node_models, chunk)


def _backfill_graph_chunk(graph_model, node_models, graph_ids):
    # Node ids come from one sequence shared by every node table, so they order
    # nodes of different types within a graph.
    nodes_by_graph = {graph_id: [] for graph_id in graph_ids}
    for node_model in node_models:
        rows = node_model._base_manager.filter(graph_id__in=graph_ids).only(
            "id", "graph_id", "node_name", "metadata", "node_number"
        )
        for node in rows.iterator(chunk_size=GRAPH_CHUNK_SIZE):
            nodes_by_graph[node.graph_id].append(node)

    changed_by_model = {node_model: [] for node_model in node_models}
    graphs = []
    for graph_id, nodes in nodes_by_graph.items():
        results, highest = _split_badges(
            [(node.id, node.node_name, node.metadata) for node in nodes]
        )
        for node, (node_name, node_number, metadata) in zip(nodes, results):
            node.node_name = node_name
            node.node_number = node_number
            node.metadata = metadata
            changed_by_model[type(node)].append(node)
        graphs.append(graph_model(id=graph_id, node_number_seq=highest))

    for node_model, nodes in changed_by_model.items():
        node_model._base_manager.bulk_update(
            nodes, ["node_name", "node_number", "metadata"], batch_size=GRAPH_CHUNK_SIZE
        )
    graph_model._base_manager.bulk_update(graphs, ["node_number_seq"], batch_size=GRAPH_CHUNK_SIZE)


def _rewrite_snapshot(snapshot):
    """Return the snapshot with its numbered nodes rewritten, or None when nothing changed."""
    nodes = snapshot.get("nodes") if isinstance(snapshot, dict) else None
    if not isinstance(nodes, list):
        return None
    numbered = [
        (position, node)
        for position, node in enumerate(nodes)
        if isinstance(node, dict) and node.get("node_type") in NUMBERED_SNAPSHOT_NODE_TYPES
    ]
    if not numbered:
        return None

    # Snapshot ids are the live ids at save time; a node without one sorts last,
    # in list order.
    results, _highest = _split_badges(
        [
            (
                (0, node["id"], position)
                if type(node.get("id")) is int
                else (1, 0, position),
                node.get("node_name"),
                node.get("metadata"),
            )
            for position, node in numbered
        ]
    )
    rewritten_nodes = list(nodes)
    for (position, node), (node_name, node_number, metadata) in zip(numbered, results):
        rewritten = {**node, "node_number": node_number}
        if "node_name" in node:
            rewritten["node_name"] = node_name
        if "metadata" in node:
            rewritten["metadata"] = metadata
        rewritten_nodes[position] = rewritten
    return {**snapshot, "nodes": rewritten_nodes}


def _rewrite_version_snapshots(apps):
    version_model = apps.get_model("tables", "GraphVersion")
    versions = version_model._base_manager.order_by("id").only("id", "snapshot")
    pending = []
    for version in versions.iterator(chunk_size=SNAPSHOT_BATCH_SIZE):
        rewritten = _rewrite_snapshot(version.snapshot)
        if rewritten is None:
            continue
        version.snapshot = rewritten
        pending.append(version)
        if len(pending) == SNAPSHOT_BATCH_SIZE:
            version_model._base_manager.bulk_update(pending, ["snapshot"])
            pending = []
    if pending:
        version_model._base_manager.bulk_update(pending, ["snapshot"])


def backfill_node_numbers(apps, schema_editor):
    _backfill_live_nodes(apps)
    _rewrite_version_snapshots(apps)


class Migration(migrations.Migration):
    dependencies = [
        ("tables", "0271_node_number"),
    ]

    operations = [
        # Reverse is a no-op: the old " #N" suffixes and metadata["nodeNumber"] values
        # cannot be rebuilt exactly (a name whose suffix disagreed with its metadata
        # kept its suffix, and duplicates were renumbered), and 0271's reverse drops
        # node_number and node_number_seq anyway.
        migrations.RunPython(backfill_node_numbers, migrations.RunPython.noop),
    ]
