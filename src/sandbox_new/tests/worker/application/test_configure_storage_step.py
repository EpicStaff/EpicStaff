"""Behavior of the storage configuration step.

It only acts for a job that asked for storage, it builds the child's storage
environment from the credentials the job carries, and it refuses to launch a job whose
storage access is incomplete rather than handing the child half a configuration. That
refusal is the producer's bug, so the user sees a generic server error and the reason
is only logged.
"""

import json

import pytest

from worker.application.steps import ConfigureStorageStep
from worker.domain.models import StorageCredentials
from tests.builders import make_context, make_worker_job
from tests.public_errors import SERVER_ERROR, logged_with, reference_in

STORAGE_ENDPOINT = "http://localhost:9000"
STORAGE_BUCKET = "sandbox"
ACCESS_KEY = "ISSUEDACCESSKEY12345"
SECRET_KEY = "issuedsecretkey0123456789abcdefghijklmn"


@pytest.fixture
def step() -> ConfigureStorageStep:
    return ConfigureStorageStep(
        storage_endpoint=STORAGE_ENDPOINT,
        storage_bucket=STORAGE_BUCKET,
    )


def storage_context(tmp_path, **job_fields):
    exec_dir = tmp_path / "exec-1"
    exec_dir.mkdir()
    fields = {
        "use_storage": True,
        "storage_org_prefix": "org1",
        "storage_allowed_paths": ["docs/", "reports/q1.csv"],
        "storage_credentials": StorageCredentials(
            access_key=ACCESS_KEY, secret_key=SECRET_KEY
        ),
    }
    fields.update(job_fields)
    job = make_worker_job(**fields)
    return make_context(job, exec_dir=exec_dir)


async def test_a_job_without_storage_is_left_alone(tmp_path, step):
    context = make_context(make_worker_job(use_storage=False), exec_dir=tmp_path)

    await step(context)

    assert context.env == {}
    assert context.storage_mutations_path is None
    assert context.completed is False


async def test_the_child_environment_is_built_from_the_credentials_on_the_job(tmp_path, step):
    context = storage_context(tmp_path)

    await step(context)

    assert context.env == {
        "STORAGE_ENDPOINT": STORAGE_ENDPOINT,
        "STORAGE_BUCKET_NAME": STORAGE_BUCKET,
        "STORAGE_ACCESS_KEY": ACCESS_KEY,
        "STORAGE_SECRET_KEY": SECRET_KEY,
        "STORAGE_ALLOWED_PATHS": json.dumps(["docs/", "reports/q1.csv"]),
        "STORAGE_ORG_PREFIX": "org1",
    }
    assert context.completed is False


async def test_the_mutations_file_is_pointed_into_the_exec_dir(tmp_path, step):
    context = storage_context(tmp_path)

    await step(context)

    assert context.storage_mutations_path == tmp_path / "exec-1" / "storage_mutations.json"


async def test_storage_without_credentials_fails_the_job(tmp_path, step, error_logs):
    context = storage_context(tmp_path, storage_credentials=None)

    await step(context)

    assert context.completed is True
    assert context.returncode == 1
    reference = reference_in(SERVER_ERROR, context.stderr)
    assert "storage_credentials are required" in logged_with(reference, error_logs)
    assert context.env == {}
    assert context.storage_mutations_path is None


async def test_storage_without_an_org_prefix_fails_the_job(tmp_path, step, error_logs):
    context = storage_context(tmp_path, storage_org_prefix=None)

    await step(context)

    assert context.completed is True
    assert context.returncode == 1
    reference = reference_in(SERVER_ERROR, context.stderr)
    assert "storage_org_prefix is required" in logged_with(reference, error_logs)
    assert context.env == {}
    assert context.storage_mutations_path is None
