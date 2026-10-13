"""Behavior of the storage provisioning step.

It only acts for a job that asked for storage, and it refuses to launch one with broken
or unscoped access rather than handing the child half-configured credentials.
"""

import json

import pytest

from worker.application.steps import ProvisionStorageStep
from tests.builders import make_context, make_worker_job
from tests.fakes import FAKE_ACCESS_KEY, FAKE_SECRET_KEY

STORAGE_ENDPOINT = "http://localhost:9000"
STORAGE_BUCKET = "sandbox"


@pytest.fixture
def step(storage_credentials) -> ProvisionStorageStep:
    return ProvisionStorageStep(
        storage_credentials,
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
    }
    fields.update(job_fields)
    job = make_worker_job(**fields)
    return make_context(job, exec_dir=exec_dir)


async def test_a_job_without_storage_is_left_alone(tmp_path, step, storage_credentials):
    context = make_context(make_worker_job(use_storage=False), exec_dir=tmp_path)

    await step(context)

    assert context.env == {}
    assert context.storage_credentials is None
    assert context.storage_mutations_path is None
    assert storage_credentials.provisioned == []
    assert context.completed is False


async def test_storage_without_an_org_prefix_fails_before_provisioning(
    tmp_path, step, storage_credentials
):
    context = storage_context(tmp_path, storage_org_prefix=None)

    await step(context)

    assert context.completed is True
    assert context.returncode == 1
    assert "storage_org_prefix is required" in context.stderr
    assert storage_credentials.provisioned == []


async def test_successful_provisioning_sets_every_storage_variable(tmp_path, step):
    context = storage_context(tmp_path)

    await step(context)

    assert context.env == {
        "STORAGE_ENDPOINT": STORAGE_ENDPOINT,
        "STORAGE_BUCKET_NAME": STORAGE_BUCKET,
        "STORAGE_ACCESS_KEY": FAKE_ACCESS_KEY,
        "STORAGE_SECRET_KEY": FAKE_SECRET_KEY,
        "STORAGE_ALLOWED_PATHS": json.dumps(["docs/", "reports/q1.csv"]),
        "STORAGE_ORG_PREFIX": "org1",
    }
    assert context.completed is False


async def test_successful_provisioning_records_the_credentials_for_revocation(tmp_path, step):
    context = storage_context(tmp_path)

    await step(context)

    assert context.storage_credentials.access_key == FAKE_ACCESS_KEY


async def test_successful_provisioning_points_the_mutations_file_into_the_exec_dir(
    tmp_path, step
):
    context = storage_context(tmp_path)

    await step(context)

    assert context.storage_mutations_path == tmp_path / "exec-1" / "storage_mutations.json"


async def test_the_credentials_are_scoped_to_the_job_org_and_paths(
    tmp_path, step, storage_credentials
):
    context = storage_context(tmp_path)

    await step(context)

    assert storage_credentials.provisioned == [("org1", ["docs/", "reports/q1.csv"])]


async def test_a_failing_provision_fails_the_job_and_leaves_no_partial_environment(
    tmp_path, step, storage_credentials
):
    storage_credentials.fail_provision = RuntimeError("minio is down")
    context = storage_context(tmp_path)

    await step(context)

    assert context.completed is True
    assert context.returncode == 1
    assert "Failed to provision scoped storage credentials" in context.stderr
    assert context.env == {}
    assert context.storage_credentials is None
