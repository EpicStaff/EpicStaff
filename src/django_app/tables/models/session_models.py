from typing import Any
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


# class SessionStatusHistoryItem(models.Model):
#     class SessionStatus(models.TextChoices):
#         RUN = "run"
#         PENDING = "pending"
#         WAIT_FOR_USER = "wait_for_user"
#         END = "end"
#         ERROR = "error"
#         EXPIRED = "expired"

#     session = models.ForeignKey("Session", on_delete=models.CASCADE)

#     status = models.CharField(
#         choices=SessionStatus.choices, max_length=255, blank=False, null=False
#     )
#     setted_at = models.DateTimeField(default=timezone.now)

#     def get_last_status(self, session):
#         # filter
#         return SessionStatusHistoryItem.objects.filter(session=session).last()

#     class Meta:
#         get_latest_by = ["setted_at"]


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
