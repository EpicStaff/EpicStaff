"""Delete the platform-wide default LLM and embedding config templates.

The model catalog's registry defaults replace their values, so the rows are dropped, not
moved. Migrating back recreates the empty tables; the template rows are not restored.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("tables", "0291_move_model_configs_to_ai_models"),
    ]

    operations = [
        migrations.RemoveField(model_name="defaultllmconfig", name="model"),
        migrations.DeleteModel(name="DefaultEmbeddingConfig"),
        migrations.DeleteModel(name="DefaultLLMConfig"),
    ]
