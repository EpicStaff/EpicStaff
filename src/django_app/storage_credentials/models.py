from django.conf import settings
from django.db import models
from django.db.models import CheckConstraint, Q
from tables.models import (
    PythonCodeResult,
    RealtimeAgentChat,
    Session,
)


class TemporaryStorageAccount(models.Model):
    session = models.OneToOneField(
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
    # Whose FILES permissions the account's policy was built from, so its access can
    # be revoked when that identity's permissions change. A run started with an API
    # key records the key, any other run records the user; a run with no acting
    # identity (schedule, webhook and telegram triggers) records neither.
    # A sub-flow's account also records who started the root session, whose permissions
    # bound it, in the `issued_for_root_*` fields.
    issued_for_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    issued_for_api_key = models.ForeignKey(
        "rbac.ApiKey",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    issued_for_root_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    issued_for_root_api_key = models.ForeignKey(
        "rbac.ApiKey",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    # The org-relative folders (ending in "/") and files the account's policy grants, the
    # run's own folders included. Python code can write there without reporting it, so
    # they are reconciled into the file index when the run ends. Null for accounts issued
    # before this was recorded.
    granted_folders = models.JSONField(null=True, blank=True)
    # Whether the run's writes may have the org's storage bin purged to make room, decided
    # at mint from the kind of principal acting (a plugin credential never purges, even
    # though the person it acts for is recorded above for revocation).
    may_purge_storage_bin = models.BooleanField(default=False)
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
