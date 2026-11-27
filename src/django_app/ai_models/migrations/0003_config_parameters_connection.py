"""Add the `parameters` and `connection` JSON fields that replace the configs' setting columns."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ai_models", "0002_move_content_types_from_tables"),
    ]

    operations = [
        migrations.AddField(
            model_name="embeddingconfig",
            name="connection",
            field=models.JSONField(blank=True, db_default={}, default=dict),
        ),
        migrations.AddField(
            model_name="embeddingconfig",
            name="parameters",
            field=models.JSONField(blank=True, db_default={}, default=dict),
        ),
        migrations.AddField(
            model_name="llmconfig",
            name="connection",
            field=models.JSONField(blank=True, db_default={}, default=dict),
        ),
        migrations.AddField(
            model_name="llmconfig",
            name="parameters",
            field=models.JSONField(blank=True, db_default={}, default=dict),
        ),
    ]
