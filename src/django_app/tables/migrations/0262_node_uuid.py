"""Give every flow node a stable uuid.

Each table gets the column in one step:
``ADD COLUMN uuid uuid DEFAULT gen_random_uuid() NOT NULL``. Postgres evaluates a
volatile column default once per existing row while it rewrites the table, so
every row, soft-deleted ones included, gets its own uuid.

Never add this column with only a Python ``default=uuid4`` on a populated table:
Django evaluates a Python default once and writes that single value into every
existing row. The ``db_default`` below is what makes this AddField safe.

The per-graph unique index is not created here: it must only count active rows,
and the column that tells them apart differs between the branches this migration
can run after. ``0274_node_uuid_constraint_active_flag`` adds it once both exist.
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
    ]
