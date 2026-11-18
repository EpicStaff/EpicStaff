from django.db import models
from django.db.models import CheckConstraint, Q
from tables.models import (
    PythonCodeResult,
    RealtimeAgentChat,
    Session,
)


class TemporaryStorageAccount(models.Model):
    # A session has one account, or several when its nodes carry different storage
    # grants (see `SessionCredentialService.issue_for_session`).
    session = models.ForeignKey(
        Session,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    python_code_result = models.OneToOneField(
        PythonCodeResult,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    realtime_agent_chat = models.OneToOneField(
        RealtimeAgentChat,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    # The org-relative folders (ending in "/") and files the account's policy grants, the
    # run's own folders included. Python code can write there without reporting it, so
    # they are reconciled into the file index when the run ends. Null for accounts issued
    # before this was recorded.
    granted_folders = models.JSONField(null=True, blank=True)
    # The actions the account's policy allows on the shared (attached) folders, for audit.
    # Null for accounts issued before this was recorded.
    shared_actions = models.JSONField(null=True, blank=True)
    access_key = models.CharField(max_length=255, unique=True)
    issued_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)

    class Meta:
        db_table = "storage_credentials_temp_account"
        verbose_name = "Temporary Storage Account"
        verbose_name_plural = "Temporary Storage Accounts"
        constraints = [
            CheckConstraint(
                condition=(
                    (
                        Q(session__isnull=False)
                        & Q(python_code_result__isnull=True)
                        & Q(realtime_agent_chat__isnull=True)
                    )
                    | (
                        Q(session__isnull=True)
                        & Q(python_code_result__isnull=False)
                        & Q(realtime_agent_chat__isnull=True)
                    )
                    | (
                        Q(session__isnull=True)
                        & Q(python_code_result__isnull=True)
                        & Q(realtime_agent_chat__isnull=False)
                    )
                ),
                name="exactly_one_fk_is_not_null",
            ),
        ]
