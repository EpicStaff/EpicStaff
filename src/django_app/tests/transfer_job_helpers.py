"""Running an export job end to end in a test: start it over the API, run it, read its archive."""

import io
import json
import zipfile
from dataclasses import dataclass
from uuid import UUID

from tables.import_export.archive import ENVELOPE_MEMBER
from tables.models import TransferJob
from tables.services.transfer_jobs.archive_store import TransferArchiveStore
from tables.services.transfer_jobs.runner import TransferJobRunner
from tests.storage_backend_fake import FakeStorageBackend


@dataclass
class FinishedExport:
    job: TransferJob
    # The archive's members by name; empty when the job stored no archive.
    members: dict[str, bytes]
    archive: bytes

    @property
    def envelope(self) -> dict:
        return json.loads(self.members[ENVELOPE_MEMBER])

    def upload(self, name: str = "export.zip") -> io.BytesIO:
        """The archive as a file a multipart import takes."""
        file = io.BytesIO(self.archive)
        file.name = name
        return file


def run_job(job_id) -> FinishedExport:
    """Run a queued export job with an in-memory store and return it with its archive."""
    backend = FakeStorageBackend()
    TransferJobRunner(store=TransferArchiveStore(backend=backend)).run(UUID(str(job_id)))
    job = TransferJob.objects.get(pk=job_id)
    archive = backend.objects.get(job.archive_key, b"") if job.archive_key else b""
    members = {}
    if archive:
        with zipfile.ZipFile(io.BytesIO(archive)) as opened:
            members = {name: opened.read(name) for name in opened.namelist()}
    return FinishedExport(job=job, members=members, archive=archive)


def export_via_job(client, url: str, body: dict) -> FinishedExport:
    """POST `body` to an export-jobs `url`, expect 202, and run the job it queued."""
    response = client.post(url, body, format="json")
    assert response.status_code == 202, response.content
    return run_job(response.json()["job_id"])
