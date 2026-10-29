"""Ending a realtime chat revokes its temporary storage credentials.

The realtime service calls POST /realtime-agent-chats/end/ with the system API key
when a call ends. Who may call it (and the 400) is covered in
api_tests/realtime_agent_chat_end_test.py; this file covers what ending does to
the chat's storage account. Only the storage backend's admin API is faked.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework import status

from agents.models import AgentDefinition
from rbac.models import Organization
from storage_credentials.models import TemporaryStorageAccount
from tables.models import OpenAIRealtimeConfig, RealtimeAgentChat, RealtimeAgentDefinition, Secret

from .test_run_code_storage_credentials import GATEWAY_PATH, ORG_CREDENTIALS_PATH, FakeStorageGateway


@pytest.fixture
def gateway():
    fake = FakeStorageGateway()
    with (
        patch(GATEWAY_PATH, fake),
        patch(ORG_CREDENTIALS_PATH, return_value=SimpleNamespace(access_key="org-access", secret_key="org-secret")),
    ):
        yield fake


@pytest.fixture
def chat(db):
    org = Organization.objects.create(name="Org RealtimeViewSet")
    agent_definition = AgentDefinition.objects.create(
        name="Test Agent", org_id=org.id,
        instruction_list=[{"name": "Instruction_1.md", "content": "You are a helpful assistant"}],
    )
    openai_config = OpenAIRealtimeConfig.objects.create(
        custom_name="openai_test", model_name="gpt-4-realtime-preview",
        api_key_secret=Secret.objects.create(name="openai_api_key", value="encrypted_key", org=org), org=org,
    )
    return RealtimeAgentChat.objects.create(
        rt_agent_definition=RealtimeAgentDefinition.objects.create(agent_definition=agent_definition),
        openai_config=openai_config,
        connection_key="conn-key-test-123",
    )


@pytest.fixture
def realtime_service(api_client, env_api_key):
    """The realtime service's view of Django: authenticated with the system API key."""
    raw_key, _ = env_api_key
    api_client.credentials(HTTP_X_API_KEY=raw_key)
    return api_client


def _end(client, connection_key, **fields):
    return client.post(
        reverse("realtimeagentchat-end"), data={"connection_key": connection_key, **fields}, format="json"
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("access_key", "delete_error", "revoked", "row_left"),
    [
        ("rt-temp-access-key", None, ["rt-temp-access-key"], False),
        # A failed revocation never blocks ending the chat; the manager's sweep retries it.
        ("rt-temp-access-key", RuntimeError("gateway error"), [], True),
        (None, None, [], False),
    ],
    ids=["revoked", "revoke-fails-row-kept", "no-storage-account"],
)
def test_ending_a_chat_records_it_and_revokes_its_storage_account(
    realtime_service, gateway, chat, access_key, delete_error, revoked, row_left
):
    gateway.delete_error = delete_error
    if access_key:
        TemporaryStorageAccount.objects.create(realtime_agent_chat=chat, access_key=access_key)

    response = _end(realtime_service, chat.connection_key, duration_seconds=123, end_reason="user_disconnected")

    assert response.status_code == status.HTTP_200_OK
    chat.refresh_from_db()
    assert chat.ended_at is not None
    assert (chat.duration_seconds, chat.end_reason) == (123, "user_disconnected")
    assert gateway.deleted == revoked
    assert TemporaryStorageAccount.objects.filter(realtime_agent_chat=chat).exists() is row_left


@pytest.mark.django_db
def test_unknown_connection_key_is_404(realtime_service, gateway):
    assert _end(realtime_service, "nonexistent-connection-key").status_code == status.HTTP_404_NOT_FOUND
