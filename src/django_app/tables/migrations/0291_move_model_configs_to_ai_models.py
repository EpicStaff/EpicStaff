"""Repoint the tables foreign keys at the ai_models models and drop the moved models from tables state."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('agents', '0019_llm_config_foreign_keys_to_ai_models'),
        ('ai_models', '0001_initial'),
        ('tables', '0290_systemoneconfig_openai_provider'),
    ]

    operations = [
        # State only: ai_models owns the same tables now, so neither the tables nor their
        # constraints may be dropped or altered.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name='embeddingconfig',
                    name='api_key_secret',
                ),
                migrations.RemoveField(
                    model_name='embeddingconfig',
                    name='created_by',
                ),
                migrations.RemoveField(
                    model_name='embeddingconfig',
                    name='model',
                ),
                migrations.RemoveField(
                    model_name='embeddingconfig',
                    name='org',
                ),
                migrations.RemoveField(
                    model_name='embeddingconfig',
                    name='tags',
                ),
                migrations.AlterField(
                    model_name='graphrag',
                    name='embedder',
                    field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='ai_models.embeddingconfig'),
                ),
                migrations.AlterField(
                    model_name='defaultcrewconfig',
                    name='embedding_config',
                    field=models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, to='ai_models.embeddingconfig'),
                ),
                migrations.AlterField(
                    model_name='naiverag',
                    name='embedder',
                    field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='ai_models.embeddingconfig'),
                ),
                migrations.AlterField(
                    model_name='crew',
                    name='embedding_config',
                    field=models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, to='ai_models.embeddingconfig'),
                ),
                migrations.RemoveField(
                    model_name='embeddingmodel',
                    name='created_by',
                ),
                migrations.RemoveField(
                    model_name='embeddingmodel',
                    name='embedding_provider',
                ),
                migrations.RemoveField(
                    model_name='embeddingmodel',
                    name='org',
                ),
                migrations.RemoveField(
                    model_name='embeddingmodel',
                    name='tags',
                ),
                migrations.AlterField(
                    model_name='defaultembeddingconfig',
                    name='model',
                    field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='ai_models.embeddingmodel'),
                ),
                migrations.RemoveField(
                    model_name='llmconfig',
                    name='api_key_secret',
                ),
                migrations.RemoveField(
                    model_name='llmconfig',
                    name='created_by',
                ),
                migrations.RemoveField(
                    model_name='llmconfig',
                    name='model',
                ),
                migrations.RemoveField(
                    model_name='llmconfig',
                    name='org',
                ),
                migrations.RemoveField(
                    model_name='llmconfig',
                    name='tags',
                ),
                migrations.AlterField(
                    model_name='crew',
                    name='planning_llm_config',
                    field=models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='planning_llm_config', to='ai_models.llmconfig'),
                ),
                migrations.AlterField(
                    model_name='systemoneconfig',
                    name='llm_config',
                    field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='system_one_configs', to='ai_models.llmconfig'),
                ),
                migrations.AlterField(
                    model_name='defaultagentconfig',
                    name='fcm_llm_config',
                    field=models.ForeignKey(default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='default_agent_fcm_config', to='ai_models.llmconfig'),
                ),
                migrations.AlterField(
                    model_name='templateagent',
                    name='fcm_llm_config',
                    field=models.ForeignKey(default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='fcm_template_agents', to='ai_models.llmconfig'),
                ),
                migrations.AlterField(
                    model_name='flowassistant',
                    name='llm_config',
                    field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='ai_models.llmconfig'),
                ),
                migrations.AlterField(
                    model_name='crew',
                    name='memory_llm_config',
                    field=models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='memory_llm_config', to='ai_models.llmconfig'),
                ),
                migrations.AlterField(
                    model_name='agent',
                    name='fcm_llm_config',
                    field=models.ForeignKey(default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='fcm_agents', to='ai_models.llmconfig'),
                ),
                migrations.AlterField(
                    model_name='defaultagentconfig',
                    name='llm_config',
                    field=models.ForeignKey(default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='default_agent_config', to='ai_models.llmconfig'),
                ),
                migrations.AlterField(
                    model_name='classificationdecisiontablenode',
                    name='default_llm_config',
                    field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='cdt_nodes_as_default', to='ai_models.llmconfig'),
                ),
                migrations.AlterField(
                    model_name='crew',
                    name='manager_llm_config',
                    field=models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='manager_crews', to='ai_models.llmconfig'),
                ),
                migrations.AlterField(
                    model_name='templateagent',
                    name='llm_config',
                    field=models.ForeignKey(default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='llm_template_agents', to='ai_models.llmconfig'),
                ),
                migrations.AlterField(
                    model_name='classificationdecisiontableprompt',
                    name='llm_config',
                    field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='cdt_prompts', to='ai_models.llmconfig'),
                ),
                migrations.AlterField(
                    model_name='defaultcrewconfig',
                    name='manager_llm_config',
                    field=models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='default_manager_crews', to='ai_models.llmconfig'),
                ),
                migrations.AlterField(
                    model_name='graphrag',
                    name='llm',
                    field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='ai_models.llmconfig'),
                ),
                migrations.AlterField(
                    model_name='agent',
                    name='llm_config',
                    field=models.ForeignKey(default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='llm_agents', to='ai_models.llmconfig'),
                ),
                migrations.RemoveField(
                    model_name='llmmodel',
                    name='created_by',
                ),
                migrations.RemoveField(
                    model_name='llmmodel',
                    name='llm_provider',
                ),
                migrations.RemoveField(
                    model_name='llmmodel',
                    name='org',
                ),
                migrations.RemoveField(
                    model_name='llmmodel',
                    name='tags',
                ),
                migrations.AlterField(
                    model_name='defaultllmconfig',
                    name='model',
                    field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='ai_models.llmmodel'),
                ),
                migrations.AlterField(
                    model_name='realtimemodel',
                    name='provider',
                    field=models.ForeignKey(default=None, null=True, on_delete=django.db.models.deletion.CASCADE, to='ai_models.provider'),
                ),
                migrations.AlterField(
                    model_name='realtimetranscriptionmodel',
                    name='provider',
                    field=models.ForeignKey(default=None, null=True, on_delete=django.db.models.deletion.CASCADE, to='ai_models.provider'),
                ),
                migrations.DeleteModel(
                    name='DefaultModels',
                ),
                migrations.DeleteModel(
                    name='EmbeddingConfigTag',
                ),
                migrations.DeleteModel(
                    name='EmbeddingConfig',
                ),
                migrations.DeleteModel(
                    name='EmbeddingModelTag',
                ),
                migrations.DeleteModel(
                    name='EmbeddingModel',
                ),
                migrations.DeleteModel(
                    name='LLMConfigTag',
                ),
                migrations.DeleteModel(
                    name='LLMConfig',
                ),
                migrations.DeleteModel(
                    name='LLMModelTag',
                ),
                migrations.DeleteModel(
                    name='LLMModel',
                ),
                migrations.DeleteModel(
                    name='Provider',
                ),
            ],
        ),
    ]
