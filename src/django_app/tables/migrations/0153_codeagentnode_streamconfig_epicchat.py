# Squashed migration: CodeAgentNode + stream_config + epicchat_enabled
# Replaces 0148_codeagentnode, 0149_codeagentnode_session_id,
#          0150_crewnode_stream_config_pythonnode_stream_config_and_more,
#          0151_codeagentnode_output_schema, 0152_add_epicchat_enabled_to_graph

import django.db.models.deletion
import tables.models.base_models
from django.db import migrations, models


class Migration(migrations.Migration):

    replaces = [
        ("tables", "0148_codeagentnode"),
        ("tables", "0149_codeagentnode_session_id"),
        ("tables", "0150_crewnode_stream_config_pythonnode_stream_config_and_more"),
        ("tables", "0151_codeagentnode_output_schema"),
        ("tables", "0152_add_epicchat_enabled_to_graph"),
    ]

    dependencies = [
        ("tables", "0152_alter_conditionaledge_id"),
    ]

    operations = [
        migrations.CreateModel(
            name="CodeAgentNode",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "content_hash",
                    models.CharField(editable=False, max_length=64, null=True),
                ),
                (
                    "id",
                    models.BigIntegerField(
                        db_default=tables.models.base_models.NextVal(
                            models.Value("tables_global_node_seq")
                        ),
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("node_name", models.CharField(blank=True, max_length=255)),
                ("input_map", models.JSONField(default=dict)),
                (
                    "output_variable_path",
                    models.CharField(
                        blank=True, default=None, max_length=255, null=True
                    ),
                ),
                ("agent_mode", models.CharField(default="build", max_length=10)),
                ("session_id", models.CharField(blank=True, default="", max_length=255)),
                ("system_prompt", models.TextField(blank=True, default="")),
                ("stream_handler_code", models.TextField(blank=True, default="")),
                ("libraries", models.JSONField(blank=True, default=list)),
                ("polling_interval_ms", models.IntegerField(default=1000)),
                ("silence_indicator_s", models.IntegerField(default=3)),
                ("indicator_repeat_s", models.IntegerField(default=5)),
                ("chunk_timeout_s", models.IntegerField(default=30)),
                ("inactivity_timeout_s", models.IntegerField(default=120)),
                ("max_wait_s", models.IntegerField(default=300)),
                ("stream_config", models.JSONField(blank=True, default=dict)),
                ("output_schema", models.JSONField(blank=True, default=dict)),
                (
                    "graph",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="code_agent_node_list",
                        to="tables.graph",
                    ),
                ),
                (
                    "llm_config",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="tables.llmconfig",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("graph", "node_name"),
                        name="unique_graph_node_name_for_code_agent_node",
                    )
                ],
            },
        ),
        migrations.AddField(
            model_name="crewnode",
            name="stream_config",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="pythonnode",
            name="stream_config",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="graph",
            name="epicchat_enabled",
            field=models.BooleanField(
                default=False,
                help_text="If 'True' -> flow is connected to EpicChat widget.",
            ),
        ),
    ]
