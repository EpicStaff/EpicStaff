from django.db import models
from django.db.models import Q
from django.utils import timezone

from tables.models.base_models import CrewSessionMessage
from tables.models.graph_models import GraphOrganizationUser


class SessionQuerySet(models.QuerySet):
    def visible(self) -> "SessionQuerySet":
        """Sessions a user may see: their flow exists and is not in the recycle bin.

        A session follows its flow (see `Session.soft_delete_kept_link_fields`), so a
        session of a binned flow answers like a missing one until a restore brings it
        back or a purge deletes it. Code that only records a running session's progress
        uses the unfiltered manager instead, so a run whose flow is binned mid-way
        can still record its status and messages. What it reaches through the binned
        flow's nodes (a key-value table, a subflow) is gone with them.
        """
        return self.filter(graph__active=True)

    def visible_in_org(self, org_id: int) -> "SessionQuerySet":
        """Visible sessions (see `visible`) of the flows organization `org_id` owns."""
        return self.visible().filter(graph__org_id=org_id)


class Session(models.Model):
    class SessionStatus(models.TextChoices):
        PENDING = "pending"
        RUN = "run"
        WAIT_FOR_USER = "wait_for_user"
        ERROR = "error"
        END = "end"
        STOP = "stop"
        EXPIRED = "expired"

    graph = models.ForeignKey("Graph", on_delete=models.CASCADE, null=True)
    parent_session = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        default=None,
        related_name="subgraph_sessions",
    )
    status = models.CharField(
        choices=SessionStatus.choices, max_length=255, blank=False, null=False
    )
    status_updated_at = models.DateTimeField()
    time_to_live = models.IntegerField(
        default=3600, help_text="Session lifitime duration in seconds."
    )
    finished_at = models.DateTimeField(null=True)
    status_data = models.JSONField(default=dict)
    variables = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now)
    graph_user = models.ForeignKey(
        GraphOrganizationUser, on_delete=models.SET_NULL, default=None, null=True
    )
    entrypoint = models.CharField(null=True, default=None)
    token_usage = models.JSONField(default=dict)

    # Binning the flow leaves `graph` set, so a restore brings its sessions back
    # and a purge deletes them (the FK's CASCADE). `graph_user` is binned with the
    # flow, so it is kept too; a purge applies its SET_NULL.
    # See tables/services/soft_delete.py.
    soft_delete_kept_link_fields = ("graph", "graph_user")

    # Not filtered: the runtime keeps updating sessions of a flow binned mid-run.
    # User-facing reads go through `visible()` / `visible_in_org()`.
    objects = SessionQuerySet.as_manager()

    def save(self, *args, **kwargs):
        now = timezone.now()
        is_new = self.pk is None

        if is_new:
            self.status_updated_at = now
        else:
            old = Session.objects.filter(pk=self.pk).only("status").first()
            if old and old.status != self.status:
                self.status_updated_at = now

        if (
            self.status
            in {
                self.SessionStatus.END,
                self.SessionStatus.ERROR,
                self.SessionStatus.EXPIRED,
                self.SessionStatus.STOP,
            }
            and not self.finished_at
        ):
            self.finished_at = now

        super().save(*args, **kwargs)

    def delete(self, using=None, keep_parents=False):
        result = super().delete(using, False)
        return result

    class Meta:
        get_latest_by = ["id"]
        indexes = [
            # The retention job's pick: finished root sessions, by flow, oldest first. id
            # completes its keyset order, so a batch is one index range with no sort.
            # finished_at is set once, so status and token-usage updates stay HOT-eligible.
            models.Index(
                fields=["graph", "finished_at", "id"],
                name="session_root_graph_finished",
                condition=Q(parent_session__isnull=True, finished_at__isnull=False),
            ),
        ]


class UserSessionMessage(CrewSessionMessage):
    text = models.TextField()


class AgentSessionMessage(CrewSessionMessage):
    agent = models.ForeignKey("Agent", on_delete=models.SET_NULL, null=True, default=None)
    thought = models.TextField(blank=True, default="")
    tool = models.TextField(blank=True, default=None, null=True)
    tool_input = models.TextField(blank=True, default=None, null=True)
    text = models.TextField(blank=True, default="")
    result = models.TextField(blank=True, default="")


class TaskSessionMessage(CrewSessionMessage):
    task = models.ForeignKey("Task", on_delete=models.SET_NULL, null=True, default=None)
    description = models.TextField(blank=True, default="")
    name = models.TextField(blank=True, default="")
    expected_output = models.TextField(blank=True, default="")
    raw = models.TextField(blank=True, default="")
    agent = models.TextField(blank=True, default="")


class SessionWarningMessage(models.Model):
    session = models.OneToOneField(Session, on_delete=models.CASCADE, related_name="warnings")
    messages = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now)


class SessionTrigger(models.Model):
    class TriggerType(models.TextChoices):
        MANUAL = "manual"
        SCHEDULE = "schedule"
        WEBHOOK = "webhook"
        TELEGRAM = "telegram"
        PARENT_FLOW = "parent_flow"

    session = models.OneToOneField(Session, on_delete=models.CASCADE, related_name="trigger")
    trigger_type = models.CharField(max_length=32, choices=TriggerType.choices, db_index=True)

    # snapshot — survives node/graph deletion, which the FKs do not
    node_name = models.CharField(max_length=255, null=True, default=None)

    schedule_trigger_node = models.ForeignKey(
        "ScheduleTriggerNode",
        on_delete=models.SET_NULL,
        null=True,
        default=None,
        related_name="+",
    )
    webhook_trigger_node = models.ForeignKey(
        "WebhookTriggerNode",
        on_delete=models.SET_NULL,
        null=True,
        default=None,
        related_name="+",
    )
    telegram_trigger_node = models.ForeignKey(
        "TelegramTriggerNode",
        on_delete=models.SET_NULL,
        null=True,
        default=None,
        related_name="+",
    )
    triggered_by_session = models.ForeignKey(
        Session,
        on_delete=models.SET_NULL,
        null=True,
        default=None,
        related_name="+",
    )
    triggered_by_user = models.ForeignKey(
        GraphOrganizationUser,
        on_delete=models.SET_NULL,
        null=True,
        default=None,
        related_name="+",
    )

    # non-relational bits: telegram chat_id, webhook path, ngrok config name, test-run flag
    extra = models.JSONField(default=dict)

    # The trigger nodes and the GraphOrganizationUser are binned with their flow;
    # keeping the links lets a restored session still name the node and the user that
    # started it. See Session.soft_delete_kept_link_fields.
    soft_delete_kept_link_fields = (
        "schedule_trigger_node",
        "webhook_trigger_node",
        "telegram_trigger_node",
        "triggered_by_user",
    )

    TEST_RUN_EXTRA_KEY = "test_run"

    _TRIGGER_ID_ATTNAME = {
        TriggerType.SCHEDULE: "schedule_trigger_node_id",
        TriggerType.WEBHOOK: "webhook_trigger_node_id",
        TriggerType.TELEGRAM: "telegram_trigger_node_id",
        TriggerType.PARENT_FLOW: "triggered_by_session_id",
    }

    @property
    def trigger_id(self) -> int | None:
        """Id of the entity that started the session, per trigger_type. None for MANUAL."""
        attname = self._TRIGGER_ID_ATTNAME.get(self.trigger_type)
        if attname is None:
            return None
        return getattr(self, attname, None)

    @property
    def is_test_run(self) -> bool:
        """True when a designer started the session from the editor with a hand-written payload."""
        return self.extra.get(self.TEST_RUN_EXTRA_KEY) is True


class SessionPrincipal(models.Model):
    class ActionKind(models.TextChoices):
        USER = "user"
        API_KEY_USER = "api_key_user"
        API_KEY_SYSTEM = "api_key_system"
        TRIGGER = "trigger"
        PLUGIN = "plugin"
        UNKNOWN = "unknown"

    session = models.OneToOneField(Session, on_delete=models.CASCADE, related_name="principal")

    kind = models.CharField(choices=ActionKind.choices, max_length=32, db_index=True)

    user = models.ForeignKey(
        "User",
        on_delete=models.SET_NULL,
        null=True,
        default=None,
        related_name="+",
    )
    api_key = models.ForeignKey(
        "rbac.ApiKey",
        on_delete=models.SET_NULL,
        null=True,
        default=None,
        related_name="+",
    )
    email = models.CharField(max_length=256, default=None, blank=True, null=True)
    # Set for PLUGIN runs only; `user` and `email` then name the person the plugin
    # ran the flow on behalf of, or stay empty when it ran on its own.
    plugin_identifier = models.CharField(max_length=32, default=None, blank=True, null=True)
