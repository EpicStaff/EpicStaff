from django.db import migrations


class Migration(migrations.Migration):
    """Lock the Flow Assistant persona: drop the user-editable override field."""

    dependencies = [
        ("tables", "0182_flow_assistant_org_scoping"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="flowassistant",
            name="system_prompt_override",
        ),
    ]
