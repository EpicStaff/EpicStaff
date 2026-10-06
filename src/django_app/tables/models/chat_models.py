from django.conf import settings
from django.db import models
from rbac.models.org_scoped import OrgScopedModel

from tables.models.base_models import TimestampMixin


class ChatBinding(OrgScopedModel, TimestampMixin):
    """Exposes a flow as a chat. The flow itself stays a plain inputs -> outputs flow;
    every chat-only behaviour (channel, concurrency, budget, handoff) lives here."""

    class Channel(models.TextChoices):
        WIDGET = "widget"
        TELEGRAM = "telegram"

    class ConcurrencyPolicy(models.TextChoices):
        INTERRUPT = "interrupt"
        QUEUE = "queue"

    class OnBudgetExhausted(models.TextChoices):
        HANDOFF = "handoff"
        REPLY = "reply"

    # Overrides the nullable OrgScopedModel.org: a brand-new table has nothing to backfill.
    org = models.ForeignKey(
        "rbac.Organization",
        on_delete=models.CASCADE,
        related_name="chat_bindings",
    )
    graph = models.ForeignKey("Graph", on_delete=models.CASCADE, related_name="chat_bindings")
    name = models.CharField(max_length=255)
    channel = models.CharField(max_length=16, choices=Channel.choices, default=Channel.WIDGET)
    is_active = models.BooleanField(default=True)
    concurrency_policy = models.CharField(
        max_length=16, choices=ConcurrencyPolicy.choices, default=ConcurrencyPolicy.INTERRUPT
    )
    history_window = models.PositiveIntegerField(default=20)
    # Null means unlimited.
    token_budget_per_conversation = models.PositiveIntegerField(null=True, blank=True)
    on_budget_exhausted = models.CharField(
        max_length=16, choices=OnBudgetExhausted.choices, default=OnBudgetExhausted.HANDOFF
    )
    budget_exhausted_message = models.TextField(blank=True, default="")
    handoff_enabled = models.BooleanField(default=True)

    class Meta(OrgScopedModel.Meta):
        pass


class ChatConversation(models.Model):
    """One end user's thread on a binding. Org-scoped through `binding__org_id`."""

    class Mode(models.TextChoices):
        BOT = "bot"
        AWAITING_HUMAN = "awaiting_human"
        HUMAN = "human"
        CLOSED = "closed"

    binding = models.ForeignKey(ChatBinding, on_delete=models.CASCADE, related_name="conversations")
    # Telegram chat_id or a widget/visitor id.
    external_id = models.CharField(max_length=255)
    mode = models.CharField(max_length=16, choices=Mode.choices, default=Mode.BOT)
    assigned_operator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    # The only session whose reply is accepted; a superseded run's reply is discarded.
    active_session = models.ForeignKey(
        "Session", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # Every run of this conversation; summed for the per-conversation token budget.
    sessions = models.ManyToManyField("Session", blank=True, related_name="+")
    handoff_reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_message_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["binding", "external_id"], name="unique_chat_conversation_per_binding"
            ),
        ]


class ChatMessage(models.Model):
    class Role(models.TextChoices):
        USER = "user"
        ASSISTANT = "assistant"
        OPERATOR = "operator"
        SYSTEM = "system"

    conversation = models.ForeignKey(
        ChatConversation, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=16, choices=Role.choices)
    content = models.TextField(blank=True, default="")
    # For a user message: the run that consumed it (null = not yet handed to a run).
    # For an assistant/system message: the run that produced it.
    session = models.ForeignKey(
        "Session", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    # Reply of a superseded run: kept for the operator to see, never delivered.
    interrupted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
