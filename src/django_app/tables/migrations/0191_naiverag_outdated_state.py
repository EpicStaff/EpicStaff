from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0190_graphrag_reindex_reason_graphragdocument_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="naiverag",
            name="outdated_reasons",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="naiveragdocumentconfig",
            name="outdated_reasons",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AlterField(
            model_name="naiverag",
            name="rag_status",
            field=models.CharField(
                choices=[
                    ("new", "New"),
                    ("processing", "Processing"),
                    ("completed", "Completed"),
                    ("warning", "Warning"),
                    ("failed", "Failed"),
                    ("partial", "Partial"),
                    ("outdated", "Outdated"),
                ],
                default="new",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="naiveragdocumentconfig",
            name="status",
            field=models.CharField(
                choices=[
                    ("new", "New"),
                    ("processing", "Processing"),
                    ("chunking", "Chunking"),
                    ("chunked", "Chunked"),
                    ("indexing", "Indexing"),
                    ("completed", "Completed"),
                    ("warning", "Warning"),
                    ("failed", "Failed"),
                    ("outdated", "Outdated"),
                ],
                default="new",
                max_length=20,
            ),
        ),
    ]
