"""Behavior of the storage configuration step.

It only acts for a job that asked for storage, it builds the child's storage
environment from the credentials the job carries, and it refuses to launch a job whose
storage access is incomplete rather than handing the child half a configuration.
"""

import json

import pytest

from worker.application.steps import ConfigureStorageStep
from worker.domain.models import StorageCredentials
from tests.builders import make_context, make_worker_job

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
        "STORAGE_OWN_PATHS": "[]",
    }
    assert context.completed is False


async def test_the_credential_scope_reaches_the_child_environment(tmp_path, step):
    context = storage_context(
        tmp_path,
        storage_credentials=StorageCredentials(
            access_key=ACCESS_KEY,
            secret_key=SECRET_KEY,
            shared_actions=["read", "write"],
            own_paths=["sessions/7/"],
        ),
    )

    await step(context)

    assert context.env["STORAGE_ALLOWED_ACTIONS"] == json.dumps(["read", "write"])
    assert context.env["STORAGE_OWN_PATHS"] == json.dumps(["sessions/7/"])


async def test_narrowed_to_no_actions_reaches_the_child_as_an_empty_list(tmp_path, step):
    context = storage_context(
        tmp_path,
        storage_credentials=StorageCredentials(
            access_key=ACCESS_KEY, secret_key=SECRET_KEY, shared_actions=[]
        ),
    )

    await step(context)

    assert context.env["STORAGE_ALLOWED_ACTIONS"] == "[]"


async def test_the_mutations_file_is_pointed_into_the_exec_dir(tmp_path, step):
    context = storage_context(tmp_path)

    await step(context)

    assert context.storage_mutations_path == tmp_path / "exec-1" / "storage_mutations.json"


async def test_storage_without_credentials_fails_the_job(tmp_path, step):
    context = storage_context(tmp_path, storage_credentials=None)

    await step(context)

    assert context.completed is True
    assert context.returncode == 1
    assert "storage_credentials are required" in context.stderr
    assert context.env == {}
    assert context.storage_mutations_path is None


async def test_storage_without_an_org_prefix_fails_the_job(tmp_path, step):
    context = storage_context(tmp_path, storage_org_prefix=None)

    await step(context)

    assert context.completed is True
    assert context.returncode == 1
    assert "storage_org_prefix is required" in context.stderr
    assert context.env == {}
    assert context.storage_mutations_path is None


async def test_the_remaining_storage_reaches_the_child_environment(tmp_path, step):
    context = storage_context(
        tmp_path,
        storage_credentials=StorageCredentials(
            access_key=ACCESS_KEY, secret_key=SECRET_KEY, free_bytes=0, purgeable_bytes=2048
        ),
    )

    await step(context)

    assert context.env["STORAGE_FREE_BYTES"] == "0"
    assert context.env["STORAGE_PURGEABLE_BYTES"] == "2048"


async def test_no_known_limit_sets_neither_storage_limit_variable(tmp_path, step):
    context = storage_context(tmp_path)

    await step(context)

    assert "STORAGE_FREE_BYTES" not in context.env
    assert "STORAGE_PURGEABLE_BYTES" not in context.env
