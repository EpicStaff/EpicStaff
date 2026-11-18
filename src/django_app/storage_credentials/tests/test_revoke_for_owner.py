"""Tests for the three `revoke_for_*` entry points of session_credential_service.

One per owner type (session / test run / realtime chat), plus the
null-graph session that used to blow up on `session.graph.org_id`.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from loguru import logger

from agents.models import AgentDefinition
from rbac.models import Organization
from storage_credentials.models import TemporaryStorageAccount
from storage_credentials.services.session_credential_service import session_credential_service
from tables.models import (
    Graph,
    OpenAIRealtimeConfig,
    PythonCodeResult,
    RealtimeAgentChat,
    RealtimeAgentDefinition,
    Secret,
    Session,
)

GATEWAY_PATH = "storage_credentials.services.session_credential_service.StorageAdminGateway"
ORG_CREDENTIAL_STORE_GET = (
    "storage_credentials.services.session_credential_service.org_credential_store.get"
)


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org Revoke")


@pytest.fixture
def gateway():
    """Patch the storage gateway and yield the instance the service will build."""
    instance = AsyncMock()
    instance.delete_service_account = AsyncMock()
    instance.close = AsyncMock()

    org_creds = MagicMock()
    org_creds.access_key = "org-access"
    org_creds.secret_key = "org-secret"

    with patch(GATEWAY_PATH) as gateway_class, patch(
        ORG_CREDENTIAL_STORE_GET, return_value=org_creds
    ) as store_get:
        gateway_class.return_value = instance
        instance.store_get = store_get
        yield instance


@pytest.fixture
def error_logs():
    """Collect loguru ERROR records emitted during the test."""
    records: list[str] = []
    sink_id = logger.add(records.append, level="ERROR")
    yield records
    logger.remove(sink_id)


@pytest.fixture
def realtime_chat(org, db):
    agent_definition = AgentDefinition.objects.create(
        name="Revoke Agent",
        org_id=org.id,
        description="agent",
        instruction_list=[{"name": "Instruction_1.md", "content": "be helpful"}],
    )
    rt_agent_definition = RealtimeAgentDefinition.objects.create(
        agent_definition=agent_definition
    )
    secret = Secret.objects.create(name="openai_api_key", value="encrypted", org=org)
    openai_config = OpenAIRealtimeConfig.objects.create(
        custom_name="openai_revoke",
        model_name="gpt-4-realtime-preview",
        api_key_secret=secret,
        org=org,
    )
    return RealtimeAgentChat.objects.create(
        rt_agent_definition=rt_agent_definition,
        openai_config=openai_config,
        connection_key="conn-key-revoke",
    )


def _session_owner(org, request):
    session = Session.objects.create(
        graph=Graph.objects.create(org=org, name="Revoke Graph"), status=Session.SessionStatus.END
    )
    return {"session": session}, lambda: session_credential_service.revoke_for_session(session.id)


def _test_run_owner(org, request):
    result = PythonCodeResult.objects.create(
        execution_id="exec-revoke-1", org_id=org.id, status=PythonCodeResult.Status.COMPLETED
    )
    return {"python_code_result": result}, lambda: session_credential_service.revoke_for_test_run(
        result.execution_id
    )


def _realtime_chat_owner(org, request):
    chat = request.getfixturevalue("realtime_chat")
    return {"realtime_agent_chat": chat}, lambda: session_credential_service.revoke_for_realtime_chat(chat.id)


OWNERS = pytest.mark.parametrize(
    "make_owner",
    [_session_owner, _test_run_owner, _realtime_chat_owner],
    ids=["session", "test-run", "realtime-chat"],
)


@pytest.mark.django_db
@OWNERS
def test_revoking_an_owner_deletes_its_service_account_and_row(org, gateway, request, make_owner):
    owner, revoke = make_owner(org, request)
    account = TemporaryStorageAccount.objects.create(access_key="owner-key", **owner)

    revoke()

    gateway.delete_service_account.assert_awaited_once_with("owner-key")
    # The org's own admin credentials are the ones that may delete the account.
    gateway.store_get.assert_called_once_with(org_id=org.id)
    assert not TemporaryStorageAccount.objects.filter(pk=account.pk).exists()


@pytest.mark.django_db
@OWNERS
def test_revoking_an_owner_without_an_account_contacts_no_storage(org, gateway, request, make_owner):
    _, revoke = make_owner(org, request)

    revoke()

    gateway.delete_service_account.assert_not_awaited()


@pytest.mark.django_db
def test_a_session_without_a_graph_keeps_its_row_and_logs(gateway, error_logs):
    """No graph means no reachable org: revoke must not be attempted silently, and
    the row must survive for the cleanup job."""
    session = Session.objects.create(graph=None, status=Session.SessionStatus.END)
    account = TemporaryStorageAccount.objects.create(session=session, access_key="orphan-key")

    session_credential_service.revoke_for_session(session.id)

    gateway.delete_service_account.assert_not_awaited()
    assert TemporaryStorageAccount.objects.filter(pk=account.pk).exists()
    assert any(f"session {session.id}" in message for message in error_logs)


@pytest.mark.django_db
def test_a_storage_failure_keeps_the_row_for_a_retry(org, gateway):
    session = Session.objects.create(
        graph=Graph.objects.create(org=org, name="Revoke Graph"), status=Session.SessionStatus.END
    )
    account = TemporaryStorageAccount.objects.create(session=session, access_key="failing-key")
    gateway.delete_service_account.side_effect = Exception("backend down")

    session_credential_service.revoke_for_session(session.id)

    assert TemporaryStorageAccount.objects.filter(pk=account.pk).exists()


@pytest.mark.django_db
@OWNERS
def test_revoking_an_owner_first_indexes_what_its_granted_folders_hold(
    org, gateway, request, make_owner, monkeypatch
):
    from storage_credentials.services import session_credential_service as service_module
    from tables.models import StorageFile
    from tests.storage_tests.in_memory_backend import InMemoryStorageBackend

    backend = InMemoryStorageBackend(organization_prefix="")
    monkeypatch.setattr(
        service_module, "get_storage_backend", lambda organization_prefix="": backend
    )
    backend.put_bytes(f"org_{org.id}/granted/unreported.bin", b"x" * 12)
    backend.put_bytes(f"org_{org.id}/not-granted/other.bin", b"x" * 99)
    owner, revoke = make_owner(org, request)
    TemporaryStorageAccount.objects.create(
        access_key="owner-key", granted_folders=["granted/"], **owner
    )

    revoke()

    assert {row.path: row.size for row in StorageFile.objects.filter(org=org, item_type="file")} == {
        "granted/unreported.bin": 12
    }
    gateway.delete_service_account.assert_awaited_once_with("owner-key")
