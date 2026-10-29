"""Store node_type on top-level GraphSessionMessage rows saved before crew sent it.

Until now the session export filled a missing node_type from Session.graph_schema,
which the next migration drops. This writes the type the schema gives each node name
onto the rows, so the export can rely on the stored value alone.

Only root sessions are backfilled, and only rows run at their top level: a subflow
session was given its root session's schema, and a subflow's inner rows run nodes of
another graph, so for those rows the schema names the wrong nodes.
"""

from django.db import migrations
from django.db.models import Case, F, Q, Value, When

SESSION_CHUNK_SIZE = 200

# Matches the TYPE crew stores on a node's rows: `agent_node_list` -> "AGENT",
# `webhook_trigger_node_data_list` -> "WEBHOOK_TRIGGER", `end_node` -> "END".
_NODE_LIST_SUFFIXES = ("_node_list", "_node_data_list")
_END_NODE_KEY = "end_node"
_END_NODE_TYPE = "END"


def _node_types_by_name(graph_schema: dict) -> dict[str, str]:
    node_types = {}
    end_node = graph_schema.get(_END_NODE_KEY)
    if isinstance(end_node, dict) and end_node.get("node_name"):
        node_types[end_node["node_name"]] = _END_NODE_TYPE
    for key, nodes in graph_schema.items():
        suffix = next((suffix for suffix in _NODE_LIST_SUFFIXES if key.endswith(suffix)), None)
        if suffix is None or not isinstance(nodes, list):
            continue
        node_type = key.removesuffix(suffix).upper()
        for node in nodes:
            if isinstance(node, dict) and node.get("node_name"):
                node_types[node["node_name"]] = node_type
    return node_types


def backfill_node_types(apps, schema_editor):
    Session = apps.get_model("tables", "Session")
    GraphSessionMessage = apps.get_model("tables", "GraphSessionMessage")

    top_level_rows = Q(message_data__subgraph_execution_ids__isnull=True) | Q(
        message_data__subgraph_execution_ids=[]
    )
    # Paged by id rather than .iterator(): outside a transaction the server-side cursor
    # is declared WITH HOLD, and Postgres would materialize every schema before the
    # first row came back.
    last_id = 0
    while True:
        batch = list(
            Session.objects.filter(parent_session__isnull=True, id__gt=last_id)
            .exclude(graph_schema={})
            .order_by("id")
            .only("id", "graph_schema")[:SESSION_CHUNK_SIZE]
        )
        if not batch:
            return
        for session in batch:
            node_types = _node_types_by_name(session.graph_schema or {})
            if not node_types:
                continue
            GraphSessionMessage.objects.filter(
                top_level_rows,
                session_id=session.id,
                node_type="",
                name__in=list(node_types),
            ).update(
                node_type=Case(
                    *(
                        When(name=name, then=Value(node_type))
                        for name, node_type in node_types.items()
                    ),
                    default=F("node_type"),
                )
            )
        last_id = batch[-1].id


class Migration(migrations.Migration):
    # Each session's update commits on its own, so a large message table is not held
    # locked for the whole backfill. Rerunning is safe: only untyped rows are written.
    atomic = False

    dependencies = [
        ("tables", "0272_merge_20261016_1000"),
    ]

    operations = [
        migrations.RunPython(backfill_node_types, migrations.RunPython.noop),
    ]
