from django.utils import timezone
from django.db import models
from django.core.serializers.json import DjangoJSONEncoder

from tables.models import CrewSessionMessage, GraphOrganizationUser


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
        on_delete=models.SET_NULL,
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
    graph_schema = models.JSONField(default=dict, encoder=DjangoJSONEncoder)
    graph_user = models.ForeignKey(
        GraphOrganizationUser, on_delete=models.SET_NULL, default=None, null=True
    )
    entrypoint = models.CharField(null=True, default=None)
    token_usage = models.JSONField(default=dict)

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


class UserSessionMessage(CrewSessionMessage):
    text = models.TextField()


class AgentSessionMessage(CrewSessionMessage):
    agent = models.ForeignKey(
        "Agent", on_delete=models.SET_NULL, null=True, default=None
    )
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
    session = models.OneToOneField(
        Session, on_delete=models.CASCADE, related_name="warnings"
    )
    messages = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now)


class SessionTrigger(models.Model):
    class TriggerType(models.TextChoices):
        MANUAL = "manual"
        SCHEDULE = "schedule"
        WEBHOOK = "webhook"
        TELEGRAM = "telegram"
        PARENT_FLOW = "parent_flow"

    session = models.OneToOneField(
        Session, on_delete=models.CASCADE, related_name="trigger"
    )
    trigger_type = models.CharField(
        max_length=32, choices=TriggerType.choices, db_index=True
    )

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

    # non-relational bits: telegram chat_id, webhook path, ngrok config name
    extra = models.JSONField(default=dict)

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
