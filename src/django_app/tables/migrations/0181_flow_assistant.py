import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0180_merge_20260514_1302"),
    ]

    operations = [
        migrations.CreateModel(
            name="FlowAssistant",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("system_prompt_override", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "graph",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="flow_assistant",
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
                "db_table": "tables_flowassistant",
            },
        ),
        migrations.CreateModel(
            name="FlowAssistantConversation",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("messages", models.JSONField(default=list)),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("last_message_at", models.DateTimeField(auto_now=True)),
                (
                    "flow_assistant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="conversations",
                        to="tables.flowassistant",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "tables_flowassistantconversation",
                "ordering": ["-started_at"],
            },
        ),
    ]
