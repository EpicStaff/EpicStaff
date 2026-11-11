"""Add the per-graph unique node uuid index, counting active rows only.

Created here, not in ``0262_node_uuid``: Django may run ``0262`` before or after
the recycle bin migrations that replace ``is_soft_deleted`` with ``active``, so only a
migration below their merge can name the column safely.
"""

from django.db import migrations, models


NODE_MODEL_NAMES = (
    "agentnode",
    "audiotranscriptionnode",
    "classificationdecisiontablenode",
    "decisiontablenode",
    "endnode",
    "fileextractornode",
    "graphnote",
    "keyvaluenode",
    "knowledgenode",
    "pythonnode",
    "scheduletriggernode",
    "startnode",
    "subgraphnode",
    "tasknode",
    "telegramtriggernode",
    "webhooktriggernode",
)


class Migration(migrations.Migration):
    dependencies = [
        ("tables", "0273_merge_20261019_1215"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name=model_name,
            constraint=models.UniqueConstraint(
                models.F("graph"),
                models.F("uuid"),
                condition=models.Q(active=True),
                name=f"tables_{model_name}_graph_uuid_unique",
            ),
        )
        for model_name in NODE_MODEL_NAMES
    ]
