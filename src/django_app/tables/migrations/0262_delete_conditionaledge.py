"""Remove the plain Conditional Edge feature: its rows, its orphaned code, its table.

A ConditionalEdge owned a PythonCode through a CASCADE FK pointing the other way
(edge -> code), so dropping the table leaves that code behind. The code is deleted
only when nothing else still points at it — "anything else" is derived from every
reverse relation on the historical PythonCode, so a code row shared with a node or
a tool survives. SET_NULL relations (``executions``) are an audit trail, not a
reference, and do not keep a row alive.

ConditionalEdge ids come from the global node sequence, so other rows may store one
as a node reference. Those references would dangle once the table is gone (see
0217_prune_dangling_node_references for what a dangling id breaks): edges touching
a removed id are deleted, nullable routing references to one are cleared.
"""

from functools import reduce
from operator import or_

from django.db import migrations
from django.db.models import Q
from django.db.models.deletion import SET_NULL
from loguru import logger

# (model, nullable field) pairs holding a node id, cleared when they point at a
# removed conditional edge. Snapshot as of this migration, like 0217.
NULLABLE_NODE_REFERENCES = [
    ("DecisionTableNode", "default_next_node_id"),
    ("DecisionTableNode", "next_error_node_id"),
    ("ConditionGroup", "next_node_id"),
    ("ClassificationDecisionTableNode", "default_next_node_id"),
    ("ClassificationDecisionTableNode", "next_error_node_id"),
    ("ClassificationConditionGroup", "next_node_id"),
]


def _python_code_reference_q(python_code_model, excluded_model) -> Q:
    """Match PythonCode rows that any relation other than `excluded_model` still points at."""
    return reduce(
        or_,
        (
            Q(**{f"{relation.name}__isnull": False})
            for relation in python_code_model._meta.related_objects
            if relation.related_model is not excluded_model
            and getattr(relation, "on_delete", None) is not SET_NULL
        ),
    )


def delete_conditional_edges(apps, schema_editor):
    conditional_edge_model = apps.get_model("tables", "ConditionalEdge")
    python_code_model = apps.get_model("tables", "PythonCode")
    edge_model = apps.get_model("tables", "Edge")

    # Historical models carry plain managers (see 0238), so `objects` includes
    # soft-deleted rows — they are removed too.
    rows = list(conditional_edge_model.objects.values_list("id", "python_code_id"))
    conditional_edge_ids = {row_id for row_id, _ in rows}
    python_code_ids = {python_code_id for _, python_code_id in rows}

    conditional_edge_model.objects.all().delete()

    _, deleted_edges_by_model = edge_model.objects.filter(
        Q(start_node_id__in=conditional_edge_ids) | Q(end_node_id__in=conditional_edge_ids)
    ).delete()
    deleted_edges = deleted_edges_by_model.get(edge_model._meta.label, 0)

    cleared_references = 0
    for model_name, field_name in NULLABLE_NODE_REFERENCES:
        model = apps.get_model("tables", model_name)
        cleared_references += model.objects.filter(
            **{f"{field_name}__in": conditional_edge_ids}
        ).update(**{field_name: None})

    # Runs after the conditional edges are gone, so their own FK no longer counts;
    # the relation is excluded anyway so the intent does not hinge on ordering.
    _, deleted_python_codes_by_model = (
        python_code_model.objects.filter(pk__in=python_code_ids)
        .exclude(_python_code_reference_q(python_code_model, conditional_edge_model))
        .delete()
    )
    orphaned_python_code_count = deleted_python_codes_by_model.get(
        python_code_model._meta.label, 0
    )

    # The deletes above queue deferred FK checks on tables_conditionaledge. Fire them
    # now: DeleteModel drops the table, and with it the triggers, in this same
    # transaction, which Postgres rejects at COMMIT ("could not find trigger").
    schema_editor.execute("SET CONSTRAINTS ALL IMMEDIATE")

    logger.info(
        "0262: deleted {} conditional edge(s), {} orphaned PythonCode row(s) "
        "(kept {} still referenced elsewhere), {} edge(s) touching a conditional "
        "edge, cleared {} routing reference(s)",
        len(conditional_edge_ids),
        orphaned_python_code_count,
        len(python_code_ids) - orphaned_python_code_count,
        deleted_edges,
        cleared_references,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('tables', '0261_merge_20261007_1300'),
    ]

    operations = [
        # Irreversible: the conditional edges and their code are deleted and the
        # feature has no replacement entity, so there is nothing to restore.
        migrations.RunPython(
            delete_conditional_edges, migrations.RunPython.noop, elidable=False
        ),
        migrations.DeleteModel(
            name='ConditionalEdge',
        ),
    ]
