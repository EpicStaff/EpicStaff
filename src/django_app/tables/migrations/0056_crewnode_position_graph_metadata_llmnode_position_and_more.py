# Generated by Django 5.1.3 on 2025-02-25 09:48

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0055_alter_agentpythoncodetool_agent_alter_crewnode_crew_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="crewnode",
            name="position",
            field=models.JSONField(default=dict),
        ),
        migrations.AddField(
            model_name="graph",
            name="metadata",
            field=models.JSONField(default=dict),
        ),
        migrations.AddField(
            model_name="llmnode",
            name="position",
            field=models.JSONField(default=dict),
        ),
        migrations.AddField(
            model_name="pythonnode",
            name="position",
            field=models.JSONField(default=dict),
        ),
    ]
