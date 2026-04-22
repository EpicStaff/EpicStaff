import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0136_merge_20260126_1313"),
    ]

    operations = [
        migrations.CreateModel(
            name="ClassificationDecisionTableNode",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("node_name", models.CharField(blank=True, max_length=255)),
                (
                    "pre_computation_code",
                    models.TextField(blank=True, default=None, null=True),
                ),
                ("prompts", models.JSONField(blank=True, default=dict)),
                (
                    "route_variable_name",
                    models.CharField(default="route_code", max_length=255),
                ),
                (
                    "default_next_node",
                    models.CharField(default=None, max_length=255, null=True),
                ),
                (
                    "next_error_node",
                    models.CharField(default=None, max_length=255, null=True),
                ),
                (
                    "graph",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="classification_decision_table_node_list",
                        to="tables.graph",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("graph", "node_name"),
                        name="unique_graph_node_name_for_classification_dt_node",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="ClassificationConditionGroup",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("group_name", models.CharField(max_length=255)),
                ("order", models.PositiveIntegerField(default=0)),
                (
                    "expression",
                    models.TextField(blank=True, default=None, null=True),
                ),
                (
                    "prompt_id",
                    models.CharField(
                        blank=True, default=None, max_length=255, null=True
                    ),
                ),
                (
                    "manipulation",
                    models.TextField(blank=True, default=None, null=True),
                ),
                ("continue_flag", models.BooleanField(default=False)),
                (
                    "route_code",
                    models.CharField(
                        blank=True, default=None, max_length=255, null=True
                    ),
                ),
                ("dock_visible", models.BooleanField(default=True)),
                (
                    "classification_decision_table_node",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="condition_groups",
                        to="tables.classificationdecisiontablenode",
                    ),
                ),
            ],
            options={
                "ordering": ["order"],
            },
        ),
    ]
