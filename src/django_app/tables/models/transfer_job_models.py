"""Background export and import jobs and the archives they produce or consume."""

import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from rbac.models.org_scoped import OrgScopedModel

from tables.import_export.enums import EntityType
from tables.models.base_models import TimestampMixin


class TransferJob(OrgScopedModel, TimestampMixin):
    """One export or import of flows or knowledge collections, run in the background.

    Only its creator, in its organization, may see it. Its archive lives in the
    storage bucket under `system/transfers/<id>/` until `expires_at`, when the
    sweep deletes the job and the archive together.
    """

    class Kind(models.TextChoices):
        EXPORT = "export"
        IMPORT = "import"

    class Status(models.TextChoices):
        QUEUED = "queued"
        RUNNING = "running"
        COMPLETED = "completed"
        FAILED = "failed"

    class MainEntity(models.TextChoices):
        FLOW = EntityType.GRAPH.value
        SOURCE_COLLECTION = EntityType.SOURCE_COLLECTION.value

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    main_entity = models.CharField(max_length=40, choices=MainEntity.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    # What the job was asked to do: the ids and include_knowledge of an export,
    # the import settings of an import.
    request = models.JSONField(default=dict, blank=True)
    # Storage key of the archive: the one an export wrote, or the upload an import reads.
    archive_key = models.CharField(max_length=512, blank=True, default="")
    # Name the archive is downloaded under.
    file_name = models.CharField(max_length=255, blank=True, default="")
    # Import summary, or what an export left out; set once the job completes.
    result = models.JSONField(null=True, blank=True)
    # {"code", "message"} of a failed job; never a traceback.
    error = models.JSONField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()

    class Meta(OrgScopedModel.Meta):
        indexes = [
            # The status endpoint and job list: the creator's jobs in one org.
            models.Index(fields=["org", "created_by", "-created_at"]),
            # The sweep: expired jobs and jobs left running.
            models.Index(fields=["expires_at"]),
            models.Index(fields=["status", "started_at"]),
        ]

    def save(self, *args, **kwargs):
        if self.expires_at is None:
            # created_at is only set inside save(); the two differ by microseconds.
            self.expires_at = timezone.now() + timedelta(seconds=settings.TRANSFER_ARCHIVE_TTL)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.kind} {self.main_entity} job {self.id} ({self.status})"
