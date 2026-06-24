"""
Migration 0184: Extract FlowAssistantConversation.messages (JSONField) into a
dedicated FlowAssistantMessage table, and rename the model attribute for the
legacy JSONField to _messages_legacy (db_column='messages' unchanged so the
actual column name on disk stays the same).

Forwards:
  1. RenameField messages -> _messages_legacy (db_column='messages' is set on
     the field, so no SQL column rename is emitted).
  2. CreateModel FlowAssistantMessage.
  3. RunPython: copy existing JSON arrays into rows (idempotent: skips
     conversations that already have message_rows).

Reverse:
  1. Delete all FlowAssistantMessage rows.
  2. DeleteModel FlowAssistantMessage.
  3. RenameField _messages_legacy -> messages.
"""

from django.db import migrations, models
import django.db.models.deletion


def _dict_to_message_row_kwargs(idx: int, msg: dict) -> dict:
    """Map a legacy message dict to FlowAssistantMessage field kwargs."""
    role = msg.get("role", "user")
    content = msg.get("content", "") or ""
    kwargs = {
        "message_index": idx,
        "role": role,
        "content": content,
    }
    if role == "assistant":
        kwargs["tool_calls"] = msg.get("tool_calls")
        kwargs["ef_tables"] = msg.get("ef_tables")
        kwargs["action_message"] = msg.get("action_message")
        kwargs["interrupted"] = bool(msg.get("interrupted", False))
    elif role == "tool":
        kwargs["tool_call_id"] = msg.get("tool_call_id") or None
        kwargs["name"] = msg.get("name") or None
    elif role in ("system", "user"):
        kwargs["tool_calls"] = msg.get("tool_calls")
    return kwargs


def copy_messages_to_rows(apps, schema_editor):
    """Copy existing JSON message arrays into FlowAssistantMessage rows."""
    FlowAssistantConversation = apps.get_model("tables", "FlowAssistantConversation")
    FlowAssistantMessage = apps.get_model("tables", "FlowAssistantMessage")

    for conversation in FlowAssistantConversation.objects.all():
        # Idempotent: skip if rows already exist for this conversation.
        if FlowAssistantMessage.objects.filter(conversation=conversation).exists():
            continue

        # Access the legacy column directly via the renamed field name.
        messages = getattr(conversation, "_messages_legacy", None) or []
        if not isinstance(messages, list) or not messages:
            continue

        rows = []
        for idx, msg in enumerate(messages):
            if not isinstance(msg, dict):
                continue
            row_kwargs = _dict_to_message_row_kwargs(idx, msg)
            rows.append(
                FlowAssistantMessage(
                    conversation=conversation,
                    **row_kwargs,
                )
            )
        if rows:
            FlowAssistantMessage.objects.bulk_create(rows)


def delete_message_rows(apps, schema_editor):
    """Reverse: delete all FlowAssistantMessage rows."""
    FlowAssistantMessage = apps.get_model("tables", "FlowAssistantMessage")
    FlowAssistantMessage.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0183_remove_flowassistant_system_prompt_override"),
    ]

    operations = [
        # Pin the column name to 'messages' before renaming the Python attribute.
        # This prevents RenameField from emitting an ALTER TABLE ... RENAME COLUMN.
        migrations.AlterField(
            model_name="flowassistantconversation",
            name="messages",
            field=models.JSONField(
                default=list,
                db_column="messages",
                editable=False,
            ),
        ),
        # Rename the model attribute. Because db_column='messages' is already set,
        # Django emits no SQL — only the internal state is updated.
        migrations.RenameField(
            model_name="flowassistantconversation",
            old_name="messages",
            new_name="_messages_legacy",
        ),
        # Create the new dedicated message table.
        migrations.CreateModel(
            name="FlowAssistantMessage",
            fields=[
                (
                    "id",
                    models.BigAutoField(primary_key=True, serialize=False),
                ),
                (
                    "conversation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="message_rows",
                        to="tables.flowassistantconversation",
                    ),
                ),
                ("message_index", models.PositiveIntegerField()),
                (
                    "role",
                    models.CharField(
                        choices=[
                            ("system", "system"),
                            ("user", "user"),
                            ("assistant", "assistant"),
                            ("tool", "tool"),
                        ],
                        max_length=16,
                    ),
                ),
                ("content", models.TextField(blank=True, default="")),
                ("tool_calls", models.JSONField(blank=True, null=True)),
                (
                    "tool_call_id",
                    models.CharField(blank=True, max_length=128, null=True),
                ),
                (
                    "name",
                    models.CharField(blank=True, max_length=255, null=True),
                ),
                ("ef_tables", models.JSONField(blank=True, null=True)),
                ("action_message", models.JSONField(blank=True, null=True)),
                ("interrupted", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "tables_flowassistantmessage",
                "ordering": ["message_index"],
                "indexes": [
                    models.Index(
                        fields=["conversation", "message_index"],
                        name="tables_flow_convers_a77e03_idx",
                    )
                ],
                "unique_together": {("conversation", "message_index")},
            },
        ),
        # Copy existing JSON arrays into rows.
        migrations.RunPython(
            copy_messages_to_rows,
            reverse_code=delete_message_rows,
        ),
    ]
