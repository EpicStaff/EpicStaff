"""Take over the model-config models from tables in migration state only; the tables stay as they are."""

import django.core.validators
import django.db.models.deletion
import tables.validators.finite_number_validator
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('rbac', '0013_merge_20261106_1246'),
        ('tables', '0290_systemoneconfig_openai_provider'),
        ('agents', '0018_merge_20261103_1638'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # State only: the tables keep their names (Meta.db_table), so no SQL runs.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='EmbeddingConfigTag',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('name', models.CharField()),
                        ('predefined', models.BooleanField(default=False)),
                    ],
                    options={
                        'db_table': 'tables_embeddingconfigtag',
                    },
                ),
                migrations.CreateModel(
                    name='EmbeddingModelTag',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('name', models.CharField()),
                        ('predefined', models.BooleanField(default=False)),
                    ],
                    options={
                        'db_table': 'tables_embeddingmodeltag',
                    },
                ),
                migrations.CreateModel(
                    name='LLMConfigTag',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('name', models.CharField()),
                        ('predefined', models.BooleanField(default=False)),
                    ],
                    options={
                        'db_table': 'tables_llmconfigtag',
                    },
                ),
                migrations.CreateModel(
                    name='LLMModelTag',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('name', models.CharField()),
                        ('predefined', models.BooleanField(default=False)),
                    ],
                    options={
                        'db_table': 'tables_llmmodeltag',
                    },
                ),
                migrations.CreateModel(
                    name='Provider',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('name', models.TextField(unique=True)),
                    ],
                    options={
                        'db_table': 'tables_provider',
                    },
                ),
                migrations.CreateModel(
                    name='EmbeddingModel',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('name', models.TextField()),
                        ('predefined', models.BooleanField(default=False)),
                        ('deployment', models.TextField(blank=True, null=True)),
                        ('base_url', models.TextField(blank=True, default=None, null=True)),
                        ('is_visible', models.BooleanField(default=True)),
                        ('is_custom', models.BooleanField(default=False)),
                        ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                        ('org', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='%(app_label)s_%(class)s_set', to='rbac.organization')),
                        ('tags', models.ManyToManyField(blank=True, related_name='embedding_models', to='ai_models.embeddingmodeltag')),
                        ('embedding_provider', models.ForeignKey(default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, to='ai_models.provider')),
                    ],
                    options={
                        'db_table': 'tables_embeddingmodel',
                        'abstract': False,
                    },
                ),
                migrations.CreateModel(
                    name='EmbeddingConfig',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('custom_name', models.TextField()),
                        ('task_type', models.CharField(choices=[('retrieval_document', 'Retrieval Doc')], default='retrieval_document', max_length=255)),
                        ('extra_headers', models.JSONField(blank=True, db_default={}, default=dict)),
                        ('is_visible', models.BooleanField(default=True)),
                        ('created_at', models.DateTimeField(auto_now_add=True, null=True)),
                        ('api_key_secret', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='embedding_configs', to='tables.secret')),
                        ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                        ('org', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='%(app_label)s_%(class)s_set', to='rbac.organization')),
                        ('tags', models.ManyToManyField(blank=True, related_name='embedding_configs', to='ai_models.embeddingconfigtag')),
                        ('model', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='ai_models.embeddingmodel')),
                    ],
                    options={
                        'db_table': 'tables_embeddingconfig',
                        'abstract': False,
                    },
                ),
                migrations.CreateModel(
                    name='LLMConfig',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('custom_name', models.TextField()),
                        ('temperature', models.FloatField(blank=True, default=0.5, null=True, validators=[django.core.validators.MinValueValidator(0.0), django.core.validators.MaxValueValidator(2.0)])),
                        ('top_p', models.FloatField(blank=True, default=1.0, null=True)),
                        ('stop', models.JSONField(blank=True, null=True)),
                        ('max_tokens', models.IntegerField(blank=True, default=4096, null=True, validators=[django.core.validators.MinValueValidator(500)])),
                        ('context_window', models.IntegerField(default=16000, validators=[django.core.validators.MinValueValidator(1000)])),
                        ('presence_penalty', models.FloatField(blank=True, default=0.0, null=True)),
                        ('frequency_penalty', models.FloatField(blank=True, default=0.0, null=True)),
                        ('logit_bias', models.JSONField(blank=True, null=True)),
                        ('seed', models.IntegerField(blank=True, null=True)),
                        ('logprobs', models.BooleanField(blank=True, null=True)),
                        ('top_logprobs', models.IntegerField(blank=True, null=True)),
                        ('reasoning_effort', models.CharField(blank=True, choices=[('none', 'none'), ('minimal', 'minimal'), ('low', 'low'), ('medium', 'medium'), ('high', 'high'), ('xhigh', 'xhigh'), ('max', 'max')], max_length=16, null=True)),
                        ('base_url', models.TextField(blank=True, null=True)),
                        ('api_version', models.TextField(blank=True, null=True)),
                        ('extra_headers', models.JSONField(blank=True, default=dict)),
                        ('timeout', models.FloatField(blank=True, default=120.0, null=True)),
                        ('input_cost_per_token', models.FloatField(blank=True, help_text="USD per prompt token. Null uses litellm's price map. Set together with output_cost_per_token.", null=True, validators=[tables.validators.finite_number_validator.validate_finite_number, django.core.validators.MinValueValidator(0.0)])),
                        ('output_cost_per_token', models.FloatField(blank=True, help_text="USD per completion token. Null uses litellm's price map. Set together with input_cost_per_token.", null=True, validators=[tables.validators.finite_number_validator.validate_finite_number, django.core.validators.MinValueValidator(0.0)])),
                        ('is_visible', models.BooleanField(default=True)),
                        ('created_at', models.DateTimeField(auto_now_add=True, null=True)),
                        ('api_key_secret', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='llm_configs', to='tables.secret')),
                        ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                        ('org', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='%(app_label)s_%(class)s_set', to='rbac.organization')),
                        ('tags', models.ManyToManyField(blank=True, related_name='llm_configs', to='ai_models.llmconfigtag')),
                    ],
                    options={
                        'db_table': 'tables_llmconfig',
                        'abstract': False,
                    },
                ),
                migrations.CreateModel(
                    name='DefaultModels',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                        ('org', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='%(app_label)s_%(class)s_set', to='rbac.organization')),
                        ('transcription_llm_config', models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='default_models_transcription_llm', to='tables.realtimetranscriptionconfig')),
                        ('voice_llm_config', models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='default_models_voice_llm', to='tables.realtimeconfig')),
                        ('memory_embedding_config', models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='default_models_memory_embedding', to='ai_models.embeddingconfig')),
                        ('agent_fcm_llm_config', models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='default_models_agent_fcm_llm', to='ai_models.llmconfig')),
                        ('agent_llm_config', models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='default_models_agent_llm', to='ai_models.llmconfig')),
                        ('memory_llm_config', models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='default_models_memory_llm', to='ai_models.llmconfig')),
                        ('project_manager_llm_config', models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='default_models_manager_llm', to='ai_models.llmconfig')),
                    ],
                    options={
                        'db_table': 'tables_defaultmodels',
                        'abstract': False,
                    },
                ),
                migrations.CreateModel(
                    name='LLMModel',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('name', models.TextField()),
                        ('predefined', models.BooleanField(default=False)),
                        ('description', models.TextField(blank=True, null=True)),
                        ('deployment_id', models.TextField(blank=True, help_text='Azure Deployment Name or Watsonx ID', null=True)),
                        ('api_version', models.TextField(blank=True, null=True)),
                        ('base_url', models.TextField(blank=True, null=True)),
                        ('is_visible', models.BooleanField(default=True)),
                        ('is_custom', models.BooleanField(default=False)),
                        ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                        ('org', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='%(app_label)s_%(class)s_set', to='rbac.organization')),
                        ('tags', models.ManyToManyField(blank=True, related_name='llm_models', to='ai_models.llmmodeltag')),
                        ('llm_provider', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='ai_models.provider')),
                    ],
                    options={
                        'db_table': 'tables_llmmodel',
                        'abstract': False,
                    },
                ),
                migrations.AddField(
                    model_name='llmconfig',
                    name='model',
                    field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='ai_models.llmmodel'),
                ),
                migrations.AddIndex(
                    model_name='embeddingconfig',
                    index=models.Index(fields=['org'], name='tables_embe_org_id_2a1831_idx'),
                ),
                migrations.AddConstraint(
                    model_name='embeddingconfig',
                    constraint=models.UniqueConstraint(fields=('org', 'custom_name'), name='unique_embeddingconfig_name_per_org'),
                ),
                migrations.AddIndex(
                    model_name='defaultmodels',
                    index=models.Index(fields=['org'], name='tables_defa_org_id_00fdd0_idx'),
                ),
                migrations.AddConstraint(
                    model_name='defaultmodels',
                    constraint=models.UniqueConstraint(fields=('org',), name='unique_defaultmodels_per_org'),
                ),
                migrations.AddIndex(
                    model_name='llmconfig',
                    index=models.Index(fields=['org'], name='tables_llmc_org_id_620637_idx'),
                ),
                migrations.AddConstraint(
                    model_name='llmconfig',
                    constraint=models.UniqueConstraint(fields=('org', 'custom_name'), name='unique_llmconfig_name_per_org'),
                ),
                migrations.AddConstraint(
                    model_name='llmconfig',
                    constraint=models.CheckConstraint(condition=models.Q(models.Q(('input_cost_per_token__isnull', True), ('output_cost_per_token__isnull', True)), models.Q(('input_cost_per_token__isnull', False), ('output_cost_per_token__isnull', False)), _connector='OR'), name='llmconfig_token_prices_set_together'),
                ),
                migrations.AddIndex(
                    model_name='llmmodel',
                    index=models.Index(fields=['org'], name='tables_llmm_org_id_b6b1a6_idx'),
                ),
                migrations.AddConstraint(
                    model_name='llmmodel',
                    constraint=models.UniqueConstraint(fields=('org', 'name', 'llm_provider'), name='unique_llmmodel_name_provider_per_org'),
                ),
                migrations.AddConstraint(
                    model_name='llmmodel',
                    constraint=models.UniqueConstraint(condition=models.Q(('org__isnull', True)), fields=('name', 'llm_provider'), name='unique_llmmodel_name_provider_builtin'),
                ),
                migrations.AddIndex(
                    model_name='embeddingmodel',
                    index=models.Index(fields=['org'], name='tables_embe_org_id_4cb2cf_idx'),
                ),
                migrations.AddConstraint(
                    model_name='embeddingmodel',
                    constraint=models.UniqueConstraint(fields=('org', 'name', 'embedding_provider'), name='unique_embeddingmodel_name_provider_per_org'),
                ),
                migrations.AddConstraint(
                    model_name='embeddingmodel',
                    constraint=models.UniqueConstraint(condition=models.Q(('org__isnull', True)), fields=('name', 'embedding_provider'), name='unique_embeddingmodel_name_provider_builtin'),
                ),
            ],
        ),
    ]
