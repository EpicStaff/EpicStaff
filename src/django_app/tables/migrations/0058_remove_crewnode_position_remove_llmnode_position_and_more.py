# Generated by Django 5.1.3 on 2025-02-26 09:10

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0057_graph_description_alter_defaultllmconfig_max_tokens"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="crewnode",
            name="position",
        ),
        migrations.RemoveField(
            model_name="llmnode",
            name="position",
        ),
        migrations.RemoveField(
            model_name="pythonnode",
            name="position",
        ),
    ]
