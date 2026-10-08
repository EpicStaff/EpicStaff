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
        organization_id=org.id,
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


@pytest.mark.django_db
class TestRevokeForSession:
    def test_revokes_and_deletes_row(self, org, gateway):
        graph = Graph.objects.create(org=org, name="Revoke Graph")
        session = Session.objects.create(graph=graph, status=Session.SessionStatus.END)
        account = TemporaryStorageAccount.objects.create(
            session=session, access_key="session-key"
        )

        session_credential_service.revoke_for_session(session.id)

        gateway.delete_service_account.assert_awaited_once_with("session-key")
        gateway.store_get.assert_called_once_with(org_id=org.id)
        assert not TemporaryStorageAccount.objects.filter(pk=account.pk).exists()

    def test_null_graph_logs_error_and_keeps_row(self, gateway, error_logs):
        """A session with no graph has no reachable org: revoke must not be
        attempted silently, and the row must survive for the cleanup job."""
        session = Session.objects.create(graph=None, status=Session.SessionStatus.END)
        account = TemporaryStorageAccount.objects.create(
            session=session, access_key="orphan-key"
        )

        session_credential_service.revoke_for_session(session.id)

        gateway.delete_service_account.assert_not_awaited()
        assert TemporaryStorageAccount.objects.filter(pk=account.pk).exists()
        assert any(f"session {session.id}" in message for message in error_logs)

    def test_missing_account_is_noop(self, org, gateway):
        graph = Graph.objects.create(org=org, name="Revoke Graph")
        session = Session.objects.create(graph=graph, status=Session.SessionStatus.END)

        session_credential_service.revoke_for_session(session.id)

        gateway.delete_service_account.assert_not_awaited()

    def test_backend_failure_keeps_row(self, org, gateway):
        graph = Graph.objects.create(org=org, name="Revoke Graph")
        session = Session.objects.create(graph=graph, status=Session.SessionStatus.END)
        account = TemporaryStorageAccount.objects.create(
            session=session, access_key="failing-key"
        )
        gateway.delete_service_account.side_effect = Exception("backend down")

        session_credential_service.revoke_for_session(session.id)

        assert TemporaryStorageAccount.objects.filter(pk=account.pk).exists()


@pytest.mark.django_db
class TestRevokeForTestRun:
    def test_revokes_and_deletes_row(self, org, gateway):
        result = PythonCodeResult.objects.create(
            execution_id="exec-revoke-1",
            org_id=org.id,
            status=PythonCodeResult.Status.COMPLETED,
        )
        account = TemporaryStorageAccount.objects.create(
            python_code_result=result, access_key="test-run-key"
        )

        session_credential_service.revoke_for_test_run(result.execution_id)

        gateway.delete_service_account.assert_awaited_once_with("test-run-key")
        gateway.store_get.assert_called_once_with(org_id=org.id)
        assert not TemporaryStorageAccount.objects.filter(pk=account.pk).exists()

    def test_missing_account_is_noop(self, gateway):
        session_credential_service.revoke_for_test_run("exec-that-never-stored-anything")

        gateway.delete_service_account.assert_not_awaited()


@pytest.mark.django_db
class TestRevokeForRealtimeChat:
    def test_revokes_and_deletes_row(self, org, realtime_chat, gateway):
        account = TemporaryStorageAccount.objects.create(
            realtime_agent_chat=realtime_chat, access_key="realtime-key"
        )

        session_credential_service.revoke_for_realtime_chat(realtime_chat.id)

        gateway.delete_service_account.assert_awaited_once_with("realtime-key")
        gateway.store_get.assert_called_once_with(org_id=org.id)
        assert not TemporaryStorageAccount.objects.filter(pk=account.pk).exists()

    def test_missing_account_is_noop(self, realtime_chat, gateway):
        session_credential_service.revoke_for_realtime_chat(realtime_chat.id)

        gateway.delete_service_account.assert_not_awaited()
