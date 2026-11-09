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
    """One export or import, run in the background.

    Every export is a job that produces a `.zip`: flows, knowledge collections,
    tools, MCP tools, audit filter presets, sessions, a classification decision
    table node, or nodes picked in the flow editor (`MainEntity.FLOW_NODES`).
    Imports run as jobs only for flows and knowledge collections; the others
    import synchronously.

    Only its creator, in its organization, may see it. Its archive lives in the
    storage bucket under `system/transfers/<id>/` until `expires_at`, when the
    sweep deletes the job and the archive together; an export's archive goes
    earlier once its creator has newer ones (`MAX_STORED_EXPORTS_PER_USER`), and
    the creator may delete a job that is not running.
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
        PYTHON_CODE_TOOL = EntityType.PYTHON_CODE_TOOL.value
        MCP_TOOL = EntityType.MCP_TOOL.value
        AUDIT_FILTER_PRESET = EntityType.AUDIT_FILTER_PRESET.value
        SESSION = EntityType.SESSION.value
        CLASSIFICATION_DECISION_TABLE_NODE = EntityType.CLASSIFICATION_DECISION_TABLE_NODE.value
        # Nodes exported from the flow editor (a partial export of one flow).
        FLOW_NODES = "FlowNodes"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    main_entity = models.CharField(max_length=40, choices=MainEntity.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    # What the job list shows: the exported item's name, a count such as "3 tools",
    # or the uploaded file's name of an import.
    display_name = models.CharField(max_length=255, blank=True, default="")
    # What the job was asked to do: the ids and include_knowledge of an export,
    # the import settings of an import.
    request = models.JSONField(default=dict, blank=True)
    # Storage key of the archive: the one an export wrote, or the upload an import reads.
    # Emptied when a completed export's archive is deleted for newer ones.
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
