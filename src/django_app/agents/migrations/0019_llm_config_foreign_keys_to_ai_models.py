"""Point the agent definition LLM config foreign keys at ai_models.LLMConfig in migration state only."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('agents', '0018_merge_20261103_1638'),
        ('ai_models', '0001_initial'),
    ]

    operations = [
        # State only: the referenced table is unchanged, so the database constraints stay as they are.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name='agentdefinition',
                    name='fallback_llm_config',
                    field=models.ForeignKey(default=None, help_text='Optional LLM used instead of llm_config when the primary fails with a transient error. Must differ from llm_config; requires llm_config.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='fallback_agent_definitions', to='ai_models.llmconfig'),
                ),
                migrations.AlterField(
                    model_name='agentdefinition',
                    name='fcm_llm_config',
                    field=models.ForeignKey(default=None, help_text='Optional dedicated LLM for function/tool-call routing. Falls back to llm_config when null.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='fcm_agent_definitions', to='ai_models.llmconfig'),
                ),
                migrations.AlterField(
                    model_name='agentdefinition',
                    name='llm_config',
                    field=models.ForeignKey(default=None, help_text='Primary LLM used for reasoning and tool selection.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='agent_definitions', to='ai_models.llmconfig'),
                ),
            ],
        ),
    ]
