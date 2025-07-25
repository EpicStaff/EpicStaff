# Generated by Django 5.1.3 on 2025-06-27 12:17

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0096_alter_defaulttoolconfig_embedding_config_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="graph",
            name="persistent_variables",
            field=models.BooleanField(
                default=False, help_text="Use variables from last session."
            ),
        ),
    ]
