"""Give every flow node a stable uuid.

Each table gets the column in one step:
``ADD COLUMN uuid uuid DEFAULT gen_random_uuid() NOT NULL``. Postgres evaluates a
volatile column default once per existing row while it rewrites the table, so
every row, soft-deleted ones included, gets its own uuid.

Never add this column with only a Python ``default=uuid4`` on a populated table:
Django evaluates a Python default once and writes that single value into every
existing row. The ``db_default`` below is what makes this AddField safe.
"""

import uuid

import django.contrib.postgres.functions
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
        ("tables", "0261_merge_20261007_1300"),
    ]

    operations = [
        *(
            migrations.AddField(
                model_name=model_name,
                name="uuid",
                field=models.UUIDField(
                    db_default=django.contrib.postgres.functions.RandomUUID(),
                    default=uuid.uuid4,
                    editable=False,
                ),
            )
            for model_name in NODE_MODEL_NAMES
        ),
        *(
            migrations.AddConstraint(
                model_name=model_name,
                constraint=models.UniqueConstraint(
                    models.F("graph"),
                    models.F("uuid"),
                    condition=models.Q(("is_soft_deleted", False)),
                    name=f"tables_{model_name}_graph_uuid_unique",
                ),
            )
            for model_name in NODE_MODEL_NAMES
        ),
    ]
