"""A new transfer job: queued, identified by a UUID, and kept for the archive TTL."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from tables.models import TransferJob

TTL_SECONDS = 3600


@pytest.fixture(autouse=True)
def archive_ttl(settings):
    settings.TRANSFER_ARCHIVE_TTL = TTL_SECONDS


@pytest.mark.django_db
def test_a_new_job_is_queued_and_expires_after_the_ttl(default_org):
    job = TransferJob.objects.create(
        org=default_org, kind=TransferJob.Kind.EXPORT, main_entity=TransferJob.MainEntity.FLOW
    )

    job.refresh_from_db()
    assert isinstance(job.id, uuid.UUID)
    assert job.status == TransferJob.Status.QUEUED
    assert (job.request, job.result, job.error, job.started_at, job.finished_at) == (
        {},
        None,
        None,
        None,
        None,
    )
    lifetime = job.expires_at - job.created_at
    assert timedelta(seconds=TTL_SECONDS) - timedelta(seconds=1) < lifetime
    assert lifetime <= timedelta(seconds=TTL_SECONDS)


@pytest.mark.django_db
def test_an_explicit_expiry_is_kept(default_org):
    expires_at = datetime(2030, 1, 1, tzinfo=UTC)

    job = TransferJob.objects.create(
        org=default_org,
        kind=TransferJob.Kind.IMPORT,
        main_entity=TransferJob.MainEntity.SOURCE_COLLECTION,
        expires_at=expires_at,
    )

    job.refresh_from_db()
    assert job.expires_at == expires_at


def test_main_entities_are_the_export_file_types():
    assert set(TransferJob.MainEntity.values) == {"Flow", "SourceCollection"}
