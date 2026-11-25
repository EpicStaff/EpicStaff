"""An organization over its storage quota gets no storage credentials for a run.

Run code writes straight to the store, past the upload quota check, so the credentials are
the gate: the run is refused with 409 `organization_storage_full` and leaves nothing behind.
At exactly the quota the organization is not over it, and the run starts.

Real services, endpoints and database; only the storage backend's admin API and the sandbox
are replaced.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from agents.models import AgentDefinition, Surface
from agents.models.agent_models import AgentDefaultSurface, SurfacePlace
from agents.models.surface_models import SurfacePythonTool, SurfaceStorageItem, ToolMode
from storage_credentials.exceptions import OrganizationStorageFullError
from storage_credentials.models import TemporaryStorageAccount
from tables.models import Graph, PythonCode, PythonCodeResult, PythonCodeTool, Session, StorageFile
from tables.models.realtime_models import RealtimeAgentChat, RealtimeAgentDefinition
from tables.services.run_python_code_service import MAX_STORED_RESULTS

from .test_run_code_storage_credentials import GATEWAY_PATH, ORG_CREDENTIALS_PATH, FakeStorageGateway
from .test_storage_grant_accounts import _issue

QUOTA = 1000
STORAGE_FULL = {
    "status_code": 409,
    "code": "organization_storage_full",
    "message": (
        "Your organization's file storage is full. Free up space or empty the recycle bin, "
        "then run again."
    ),
}


@pytest.fixture(autouse=True)
def _storage_settings(settings):
    settings.STORAGE_BUCKET_NAME = "bucket"
    settings.ORG_STORAGE_QUOTA = QUOTA


@pytest.fixture
def gateway():
    fake = FakeStorageGateway()
    with (
        patch(GATEWAY_PATH, fake),
        patch(
            ORG_CREDENTIALS_PATH,
            return_value=SimpleNamespace(access_key="org-access", secret_key="org-secret"),
        ),
    ):
        yield fake


def _fill_storage(org, size: int) -> None:
    StorageFile.objects.create(org=org, path="big.bin", name="big.bin", item_type="file", size=size)


@pytest.fixture
def storage_code(default_org):
    python_code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    PythonCodeTool.objects.create(python_code=python_code, org_id=default_org.id, use_storage=True)
    return python_code


def _run_code(auth_client, python_code):
    return auth_client.post(
        "/api/run-python-code/",
        {"python_code_id": python_code.pk, "variables": {}},
        format="json",
    )


@pytest.mark.django_db
def test_a_code_run_with_storage_is_refused_when_storage_is_full(
    gateway, sandbox_intake, storage_code, default_org, auth_client
):
    _fill_storage(default_org, QUOTA + 1)

    response = _run_code(auth_client, storage_code)

    assert response.status_code == 409, response.content
    assert response.json() == STORAGE_FULL
    assert not PythonCodeResult.objects.exists()
    assert gateway.created == []
    assert sandbox_intake.bodies == []


@pytest.mark.django_db
def test_a_code_run_with_storage_starts_at_exactly_the_quota(
    gateway, sandbox_intake, storage_code, default_org, auth_client
):
    _fill_storage(default_org, QUOTA)

    response = _run_code(auth_client, storage_code)

    assert response.status_code < 300, response.content
    assert PythonCodeResult.objects.count() == 1
    assert len(gateway.created) == 1
    assert len(sandbox_intake.bodies) == 1


@pytest.mark.django_db
def test_a_refused_code_run_evicts_none_of_the_stored_results(
    gateway, sandbox_intake, storage_code, default_org, auth_client
):
    """The oldest results make room for a new one only once the run is admitted."""
    PythonCodeResult.objects.bulk_create(
        PythonCodeResult(execution_id=f"old-{index}", org_id=default_org.id)
        for index in range(MAX_STORED_RESULTS)
    )
    _fill_storage(default_org, QUOTA + 1)

    _run_code(auth_client, storage_code)

    assert PythonCodeResult.objects.count() == MAX_STORED_RESULTS


@pytest.mark.django_db
def test_a_code_run_without_storage_still_runs_when_storage_is_full(
    gateway, sandbox_intake, default_org, auth_client
):
    python_code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    PythonCodeTool.objects.create(python_code=python_code, org_id=default_org.id, use_storage=False)
    _fill_storage(default_org, QUOTA + 1)

    response = _run_code(auth_client, python_code)

    assert response.status_code < 300, response.content
    assert len(sandbox_intake.bodies) == 1


@pytest.mark.django_db
def test_a_full_organization_s_quota_does_not_refuse_another_organization(
    gateway, sandbox_intake, storage_code, default_org, auth_client
):
    from rbac.models import Organization

    _fill_storage(Organization.objects.create(name="full-org"), QUOTA + 1)

    response = _run_code(auth_client, storage_code)

    assert response.status_code < 300, response.content


@pytest.mark.django_db
def test_a_flow_session_with_storage_nodes_mints_nothing_when_storage_is_full(
    gateway, default_org
):
    """`run_session` handles this refusal as any run admission refusal (`test_run_admission`)."""
    session = Session.objects.create(
        graph=Graph.objects.create(org=default_org, name="flow"),
        status=Session.SessionStatus.PENDING,
    )
    _fill_storage(default_org, QUOTA + 1)

    with pytest.raises(OrganizationStorageFullError):
        _issue(session, default_org, [None])

    assert gateway.created == []
    assert not TemporaryStorageAccount.objects.exists()


@pytest.mark.django_db
def test_a_realtime_chat_with_a_storage_tool_is_refused_and_leaves_no_chat(
    gateway, default_org, auth_client, redis_client_mock, openai_realtime_provider_config
):
    agent_definition = AgentDefinition.objects.create(org=default_org, name="voice")
    RealtimeAgentDefinition.objects.create(
        agent_definition=agent_definition, openai_config=openai_realtime_provider_config
    )
    surface = Surface.objects.create(org=default_org, name="voice-surface", instructions="")
    AgentDefaultSurface.objects.create(
        agent_definition=agent_definition, surface=surface, place=SurfacePlace.REALTIME
    )
    storage_tool = PythonCodeTool.objects.create(
        name="files",
        description="",
        use_storage=True,
        python_code=PythonCode.objects.create(code="def main(**kw): return kw"),
    )
    SurfacePythonTool.objects.create(surface=surface, python_tool=storage_tool, mode=ToolMode.ALLOW)
    granted = StorageFile.objects.create(
        org=default_org, path="reports/big.bin", name="big.bin", item_type="file", size=QUOTA + 1
    )
    SurfaceStorageItem.objects.create(surface=surface, storage_file=granted, can_view="allow")

    response = auth_client.post(
        "/api/init-realtime/", {"agent_definition_id": agent_definition.pk}, format="json"
    )

    assert response.status_code == 409, response.content
    assert response.json() == STORAGE_FULL
    assert not RealtimeAgentChat.objects.exists()
    assert gateway.created == []
    redis_client_mock.publish.assert_not_called()
