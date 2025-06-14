# Generated by Django 5.1.1 on 2024-10-03 11:03

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0005_remove_crew_manager_llm_config_alter_agent_tools_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="crew",
            name="manager_llm_model",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE, to="tables.llmmodel"
            ),
        ),
        migrations.AddField(
            model_name="crew",
            name="manager_llm_config",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="tables.configllm",
            ),
        ),
        migrations.DeleteModel(
            name="ManagerLLMModel",
        ),
    ]
