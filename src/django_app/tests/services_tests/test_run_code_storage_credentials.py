"""Temporary storage credentials for a bare test run (/run-python-code/).

A test run whose code is a storage tool gets its own service account, scoped to
`test-runs/<execution id>/` under the org's prefix, handed to the sandbox on the
submission and revoked when the result comes back. The storage backend's admin
API is the external boundary, replaced by FakeStorageGateway.
"""

import json
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from pydantic import BaseModel, ValidationError

from rbac.models import Organization
from src.shared.models import CodeResultData
from storage_credentials.models import TemporaryStorageAccount
from tables.models import PythonCode, PythonCodeResult, PythonCodeTool
from tables.services.redis_pubsub import RedisPubSub
from tables.services.run_python_code_service import RunPythonCodeService

GATEWAY_PATH = "storage_credentials.services.session_credential_service.StorageAdminGateway"
ORG_CREDENTIALS_PATH = "storage_credentials.services.session_credential_service.org_credential_store.get"


class FakeStorageGateway:
    """Records the service accounts minted and deleted in the storage backend."""

    def __init__(self, delete_error: Exception | None = None):
        self.created: list[dict] = []
        self.deleted: list[str] = []
        self.delete_error = delete_error

    def __call__(self, *args, **kwargs):
        return self

    async def create_service_account(self, **kwargs):
        self.created.append(kwargs)
        return f"temp-access-{len(self.created)}", f"temp-secret-{len(self.created)}"

    async def delete_service_account(self, access_key):
        if self.delete_error is not None:
            raise self.delete_error
        self.deleted.append(access_key)

    async def close(self):
        pass


@pytest.fixture
def gateway():
    fake = FakeStorageGateway()
    with (
        patch(GATEWAY_PATH, fake),
        patch(ORG_CREDENTIALS_PATH, return_value=SimpleNamespace(access_key="org-access", secret_key="org-secret")),
    ):
        yield fake


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org TestRunStorage")


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(email="testrun@example.com", password="StrongPass123!")


@pytest.fixture
def python_code(db):
    return PythonCode.objects.create(code="def main(**kw): return kw", entrypoint="main", global_kwargs={})


def _run(python_code, org, user, sandbox_intake) -> tuple[str, list[dict]]:
    """Start a test run; returns its execution id and the bodies it submitted."""
    execution_id = RunPythonCodeService().run_code(
        python_code_id=python_code.pk, varaibles={}, organization_id=org.id, user=user
    )
    return execution_id, sandbox_intake.bodies


def _temporary_accounts(execution_id):
    return TemporaryStorageAccount.objects.filter(python_code_result__execution_id=execution_id)


@pytest.mark.django_db
def test_storage_tool_run_gets_credentials_scoped_to_its_own_folder(
    gateway, org, user, python_code, sandbox_intake
):
    PythonCodeTool.objects.create(python_code=python_code, org_id=org.id, use_storage=True)

    execution_id, submitted = _run(python_code, org, user, sandbox_intake)

    (task,) = submitted
    assert task["storage_credentials"] == {"access_key": "temp-access-1", "secret_key": "temp-secret-1"}
    assert list(_temporary_accounts(execution_id).values_list("access_key", flat=True)) == ["temp-access-1"]
    (minted,) = gateway.created
    assert f"/org_{org.id}/test-runs/{execution_id}/*" in json.dumps(minted["policy"])


@pytest.mark.django_db
@pytest.mark.parametrize("storage_tool_org", [None, "other"], ids=["no-storage-tool", "storage-tool-in-another-org"])
def test_run_without_storage_in_its_org_mints_nothing(
    gateway, org, user, python_code, storage_tool_org, sandbox_intake
):
    """use_storage is resolved per org: another org's storage tool for the same code doesn't count."""
    if storage_tool_org:
        other_org = Organization.objects.create(name="Org Other")
        PythonCodeTool.objects.create(python_code=python_code, org_id=other_org.id, use_storage=True)

    execution_id, submitted = _run(python_code, org, user, sandbox_intake)

    (task,) = submitted
    assert (task["use_storage"], task["storage_credentials"]) == (False, None)
    assert gateway.created == []
    assert not _temporary_accounts(execution_id).exists()
    assert PythonCodeResult.objects.filter(execution_id=execution_id).exists()


def _validation_error() -> ValidationError:
    class Probe(BaseModel):
        value: int

    try:
        Probe(value="not-an-int")
    except ValidationError as error:
        return error
    raise AssertionError("expected a ValidationError")


@pytest.mark.django_db
def test_task_that_cannot_be_built_revokes_the_credentials_it_minted(
    gateway, org, user, python_code, sandbox_intake
):
    """Nothing is submitted, so no result will ever come back to revoke them."""
    PythonCodeTool.objects.create(python_code=python_code, org_id=org.id, use_storage=True)

    with patch("tables.services.run_python_code_service.CodeTaskData", side_effect=_validation_error()):
        execution_id, submitted = _run(python_code, org, user, sandbox_intake)

    assert submitted == []
    assert PythonCodeResult.objects.get(execution_id=execution_id).status == PythonCodeResult.Status.ERROR
    assert gateway.deleted == ["temp-access-1"]
    assert not _temporary_accounts(execution_id).exists()


@pytest.mark.django_db
def test_a_refused_submission_revokes_the_credentials_it_minted(
    gateway, org, user, python_code, sandbox_intake
):
    """The sandbox refused the run, so no result will come back to revoke them."""
    PythonCodeTool.objects.create(python_code=python_code, org_id=org.id, use_storage=True)
    sandbox_intake.status_code = 503

    execution_id, _ = _run(python_code, org, user, sandbox_intake)

    result = PythonCodeResult.objects.get(execution_id=execution_id)
    assert result.status == PythonCodeResult.Status.ERROR
    assert result.stderr == "Could not reach the code sandbox for this run."
    assert gateway.deleted == ["temp-access-1"]
    assert not _temporary_accounts(execution_id).exists()


@pytest.mark.django_db
def test_an_unreachable_sandbox_revokes_the_credentials_it_minted(
    gateway, org, user, python_code, sandbox_intake
):
    """A connection failure is a raw httpx error, not a ClientError: catching only
    the latter would let it escape the view and strand the run as PENDING."""
    PythonCodeTool.objects.create(python_code=python_code, org_id=org.id, use_storage=True)
    sandbox_intake.transport_error = httpx.ConnectError("connection refused")

    execution_id, _ = _run(python_code, org, user, sandbox_intake)

    result = PythonCodeResult.objects.get(execution_id=execution_id)
    assert result.status == PythonCodeResult.Status.ERROR
    assert result.stderr == "Could not reach the code sandbox for this run."
    assert gateway.deleted == ["temp-access-1"]
    assert not _temporary_accounts(execution_id).exists()


def _deliver_result(execution_id: str) -> None:
    handler = RedisPubSub()
    handler.redis_client = None
    message = CodeResultData(execution_id=execution_id, result_data="ok", stderr="", stdout="", returncode=0)
    # The handler normally runs in its own thread with its own connection.
    with patch("tables.services.redis_pubsub.close_old_connections"):
        handler.code_results_handler({"data": message.model_dump_json()})


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("access_key", "delete_error", "revoked", "row_left"),
    [
        ("temp-key", None, ["temp-key"], False),
        # The manager's backstop sweep retries a revocation that failed here.
        ("temp-key", RuntimeError("gateway error"), [], True),
        (None, None, [], False),
    ],
    ids=["revoked", "revoke-fails-row-kept", "no-temporary-account"],
)
def test_result_completes_the_run_and_revokes_its_credentials(
    gateway, org, user, python_code, access_key, delete_error, revoked, row_left
):
    gateway.delete_error = delete_error
    result = PythonCodeResult.objects.create(
        execution_id="exec-1", org_id=org.id, created_by=user, python_code=python_code,
        status=PythonCodeResult.Status.PENDING,
    )
    if access_key:
        TemporaryStorageAccount.objects.create(python_code_result=result, access_key=access_key)

    _deliver_result("exec-1")

    assert gateway.deleted == revoked
    assert _temporary_accounts("exec-1").exists() is row_left
    result.refresh_from_db()
    assert result.status == PythonCodeResult.Status.COMPLETED
