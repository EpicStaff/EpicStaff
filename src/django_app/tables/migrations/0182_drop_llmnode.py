from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("tables", "0181_merge_schedule_trigger_node"),
    ]

    operations = [
        migrations.DeleteModel(
            name="LLMNode",
        ),
    ]
