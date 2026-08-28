"""Clear node references left dangling by 0211_delete_codeagentnode.

Nodes are addressed by a global id drawn from ``tables_global_node_seq`` and stored
in plain BigIntegerFields, not ForeignKeys (see BaseGlobalNode.find_globally). The
database therefore knows nothing about these links, so dropping the CodeAgentNode
table left every edge, decision-table branch and condition group that pointed at a
code-agent node referring to an id that no longer resolves anywhere.

Symptoms: such edges are invisible in the flow editor (the loader skips endpoints it
cannot resolve), yet the graph still runs and langgraph rejects it with
``ValueError: Found edge starting at unknown node '... #N'``. Export/import, copy and
version restore fail on the same references.

Pruning is by resolvability, not by "was it a code-agent id" — the table is already
gone, so the original ids are unknowable, and any other dangling reference is equally
broken. The work is done in SQL against a UNION of the node tables rather than by
pulling every node id into Python, which would blow past Postgres' parameter limit on
a large graph set.
"""

from django.db import migrations

# Snapshot of the concrete BaseGlobalNode subclasses as of this migration. Hardcoded on
# purpose: a migration describes the schema at its point in history and must not follow
# later model changes. Models absent from the historical state are skipped.
NODE_MODELS = [
    "CrewNode",
    "PythonNode",
    "FileExtractorNode",
    "AudioTranscriptionNode",
    "SubGraphNode",
    "TaskNode",
    "AgentNode",
    "StartNode",
    "EndNode",
    "ConditionalEdge",
    "DecisionTableNode",
    "ClassificationDecisionTableNode",
    "WebhookTriggerNode",
    "TelegramTriggerNode",
    "ScheduleTriggerNode",
    "GraphNote",
]

# (model, nullable field) pairs holding a node reference — set to NULL when dangling.
# ConditionalEdge is deliberately absent: see prune_dangling_references.
NULLABLE_REFERENCES = [
    ("DecisionTableNode", "default_next_node_id"),
    ("DecisionTableNode", "next_error_node_id"),
    ("ConditionGroup", "next_node_id"),
    ("ClassificationDecisionTableNode", "default_next_node_id"),
    ("ClassificationDecisionTableNode", "next_error_node_id"),
    ("ClassificationConditionGroup", "next_node_id"),
]


def _table(apps, model_name):
    """Historical db_table for a model, or None if it no longer exists."""
    try:
        return apps.get_model("tables", model_name)._meta.db_table
    except LookupError:
        return None


def prune_dangling_references(apps, schema_editor):
    node_tables = [t for t in (_table(apps, m) for m in NODE_MODELS) if t]
    if not node_tables:
        return

    # Table names come from Django's model registry, never from user input.
    known_ids_sql = " UNION ALL ".join(f"SELECT id FROM {t}" for t in node_tables)

    with schema_editor.connection.cursor() as cursor:
        # ConditionalEdge goes first, and is deleted rather than blanked: its clean()
        # rejects any source_node_id that does not resolve — NULL included — so a
        # blanked row would be permanently unsaveable. It is itself a global node, so
        # deleting it can strand an edge that pointed at it; running it before the
        # edge sweep lets the same pass catch that, since the UNION below is a live
        # subquery rather than a snapshot.
        conditional_edge_table = _table(apps, "ConditionalEdge")
        if conditional_edge_table:
            cursor.execute(
                f"DELETE FROM {conditional_edge_table} "
                f"WHERE source_node_id IS NULL "
                f"   OR source_node_id NOT IN ({known_ids_sql})"
            )

        edge_table = _table(apps, "Edge")
        if edge_table:
            # An edge with a missing endpoint cannot be repaired — start_node_id and
            # end_node_id are NOT NULL, so the row goes.
            cursor.execute(
                f"DELETE FROM {edge_table} "
                f"WHERE start_node_id NOT IN ({known_ids_sql}) "
                f"   OR end_node_id NOT IN ({known_ids_sql})"
            )

        for model_name, field in NULLABLE_REFERENCES:
            table = _table(apps, model_name)
            if not table:
                continue
            cursor.execute(
                f"UPDATE {table} SET {field} = NULL "
                f"WHERE {field} IS NOT NULL "
                f"  AND {field} NOT IN ({known_ids_sql})"
            )


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0216_remove_crewnode_stream_config_and_more"),
    ]

    operations = [
        # Irreversible by nature: these ids pointed at rows that no longer exist, so
        # there is nothing to restore them to.
        migrations.RunPython(
            prune_dangling_references, migrations.RunPython.noop, elidable=False
        ),
    ]
