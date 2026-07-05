from django.db import models


class FlowAssistant(models.Model):
    graph = models.OneToOneField(
        "Graph",
        on_delete=models.CASCADE,
        related_name="flow_assistant",
    )
    llm_config = models.ForeignKey(
        "LLMConfig",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tables_flowassistant"

    def __str__(self):
        return f"FlowAssistant(graph_id={self.graph_id})"


class FlowAssistantConversation(models.Model):
    flow_assistant = models.ForeignKey(
        FlowAssistant,
        on_delete=models.CASCADE,
        related_name="conversations",
    )
    organization_user = models.ForeignKey(
        "OrganizationUser",
        on_delete=models.CASCADE,
        related_name="flow_assistant_conversations",
    )
    title = models.CharField(max_length=200, blank=True, default="")
    # Legacy: kept for one release as a fallback. Writes go to FlowAssistantMessage rows.
    # Drop in follow-up phase.
    _messages_legacy = models.JSONField(
        default=list,
        db_column="messages",
        editable=False,
    )
    started_at = models.DateTimeField(auto_now_add=True)
    last_message_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "tables_flowassistantconversation"
        ordering = ["-started_at"]

    def __str__(self):
        return f"FlowAssistantConversation(id={self.pk}, org_user_id={self.organization_user_id})"

    @property
    def messages(self) -> list[dict]:
        """
        Transitional compatibility shim: synthesize the legacy list-of-dicts
        from message_rows. Remove this property and the legacy JSONField
        column together in a follow-up phase.
        """
        rows = list(self.message_rows.all())
        if not rows:
            # Fall back to the legacy JSON column during the transition window
            # (e.g. a row that was never migrated, or in tests that haven't
            # yet been updated to use _make_conversation_with_messages).
            return list(self._messages_legacy or [])
        result = []
        for row in rows:
            msg: dict = {"role": row.role, "content": row.content}
            if row.role == "assistant":
                if row.tool_calls is not None:
                    msg["tool_calls"] = row.tool_calls
                if row.ef_tables is not None:
                    msg["ef_tables"] = row.ef_tables
                if row.action_message is not None:
                    msg["action_message"] = row.action_message
                if row.interrupted:
                    msg["interrupted"] = True
            elif row.role == "tool":
                if row.tool_call_id is not None:
                    msg["tool_call_id"] = row.tool_call_id
                if row.name is not None:
                    msg["name"] = row.name
            elif row.role in ("system", "user"):
                if row.tool_calls is not None:
                    msg["tool_calls"] = row.tool_calls
            result.append(msg)
        return result


class FlowAssistantMessage(models.Model):
    ROLE_SYSTEM = "system"
    ROLE_USER = "user"
    ROLE_ASSISTANT = "assistant"
    ROLE_TOOL = "tool"

    ROLE_CHOICES = [
        (ROLE_SYSTEM, "system"),
        (ROLE_USER, "user"),
        (ROLE_ASSISTANT, "assistant"),
        (ROLE_TOOL, "tool"),
    ]

    id = models.BigAutoField(primary_key=True)
    conversation = models.ForeignKey(
        FlowAssistantConversation,
        on_delete=models.CASCADE,
        related_name="message_rows",
    )
    message_index = models.PositiveIntegerField()
    role = models.CharField(max_length=16, choices=ROLE_CHOICES)
    content = models.TextField(blank=True, default="")
    # assistant only: list of OpenAI tool_call dicts
    tool_calls = models.JSONField(null=True, blank=True)
    # tool-role rows only
    tool_call_id = models.CharField(max_length=128, null=True, blank=True)
    name = models.CharField(max_length=255, null=True, blank=True)
    # assistant only
    ef_tables = models.JSONField(null=True, blank=True)
    action_message = models.JSONField(null=True, blank=True)
    # assistant only — stored as a column, not embedded in JSON
    interrupted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tables_flowassistantmessage"
        ordering = ["message_index"]
        unique_together = [("conversation", "message_index")]
        indexes = [
            models.Index(
                fields=["conversation", "message_index"],
                name="tables_flow_convers_a77e03_idx",
            ),
        ]

    def __str__(self):
        return (
            f"FlowAssistantMessage(conv={self.conversation_id}, "
            f"idx={self.message_index}, role={self.role})"
        )
