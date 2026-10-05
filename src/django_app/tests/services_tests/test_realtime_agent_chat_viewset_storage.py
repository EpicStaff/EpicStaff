"""Tests for RealtimeAgentChatViewSet.end() storage credential revocation.

Commit 5, Part 9: Realtime chat endpoint revokes temporary storage credentials.
Tests verify:
1. RealtimeAgentChatViewSet.end() revokes credentials and deletes DB row on success
2. RealtimeAgentChatViewSet.end() is no-op when no TemporaryStorageAccount exists
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from django.utils import timezone

from rbac.models import Organization
from tables.models import (
    RealtimeAgentChat,
    RealtimeAgentDefinition,
    AgentDefinition,
    OpenAIRealtimeConfig,
    Secret,
)
from tables.views.model_view_sets import RealtimeAgentChatViewSet
from storage_credentials.models import TemporaryStorageAccount
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.request import Request
from rest_framework import status


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org RealtimeViewSet")


@pytest.fixture
def agent_definition(org):
    return AgentDefinition.objects.create(
        name="Test Agent",
        organization_id=org.id,
        description="Test agent",
        instructions="You are a helpful assistant",
    )


@pytest.fixture
def rt_agent_definition(agent_definition):
    return RealtimeAgentDefinition.objects.create(
        agent_definition=agent_definition,
    )


@pytest.fixture
def realtime_agent_chat(rt_agent_definition, db):
    """Create a minimal RealtimeAgentChat with connection_key"""
    from tables.models import OpenAIRealtimeConfig
    from tables.models import Secret

    secret = Secret.objects.create(
        name="openai_api_key", value="encrypted_key"
    )
    openai_config = OpenAIRealtimeConfig.objects.create(
        name="openai_test",
        model_name="gpt-4-realtime-preview",
        api_key_secret=secret,
    )

    chat = RealtimeAgentChat.objects.create(
        rt_agent_definition=rt_agent_definition,
        openai_config=openai_config,
        connection_key="conn-key-test-123",
    )
    return chat


@pytest.fixture
def viewset():
    return RealtimeAgentChatViewSet()


@pytest.mark.django_db
class TestRealtimeAgentChatViewSetEnd:
    """Tests for RealtimeAgentChatViewSet.end() method"""

    @patch("storage_credentials.services.session_credential_service.StorageAdminGateway")
    def test_realtime_agent_chat_viewset_end_revokes_credentials(
        self, mock_gateway_class, viewset, realtime_agent_chat, org
    ):
        """RealtimeAgentChatViewSet.end() revokes temp account and deletes DB row on success"""
        # Create temporary storage account for this chat
        temp_account = TemporaryStorageAccount.objects.create(
            realtime_agent_chat=realtime_agent_chat,
            access_key="rt-temp-access-key",
        )

        # Mock the async gateway
        mock_gateway_instance = AsyncMock()
        mock_gateway_class.return_value = mock_gateway_instance
        mock_gateway_instance.delete_service_account = AsyncMock()
        mock_gateway_instance.close = AsyncMock()

        # Mock org credentials
        mock_org_creds = MagicMock()
        mock_org_creds.access_key = "org-access"
        mock_org_creds.secret_key = "org-secret"

        # Create request
        factory = APIRequestFactory()
        django_request = factory.post(
            "/api/realtime-agent-chats/end/",
            data={
                "connection_key": "conn-key-test-123",
                "duration_seconds": 123,
                "end_reason": "completed",
            },
            format="json",
        )
        request = Request(django_request)

        with patch(
            "storage_credentials.services.session_credential_service.org_credential_store.get",
            return_value=mock_org_creds,
        ):
            response = viewset.end(request)

        # Verify the response is successful
        assert response.status_code == 200

        # Verify delete_service_account was called with the correct access_key
        mock_gateway_instance.delete_service_account.assert_called_once_with(
            "rt-temp-access-key"
        )

        # Verify the TemporaryStorageAccount row was deleted
        assert not TemporaryStorageAccount.objects.filter(pk=temp_account.pk).exists()

        # Verify the chat was marked as ended
        realtime_agent_chat.refresh_from_db()
        assert realtime_agent_chat.ended_at is not None
        assert realtime_agent_chat.duration_seconds == 123
        assert realtime_agent_chat.end_reason == "completed"

    def test_realtime_agent_chat_viewset_end_no_revoke_without_temp_account(
        self, viewset, realtime_agent_chat
    ):
        """RealtimeAgentChatViewSet.end() succeeds when no TemporaryStorageAccount exists"""
        # No temporary storage account created for this chat

        factory = APIRequestFactory()
        django_request = factory.post(
            "/api/realtime-agent-chats/end/",
            data={
                "connection_key": "conn-key-test-123",
                "duration_seconds": 60,
                "end_reason": "completed",
            },
            format="json",
        )
        request = Request(django_request)

        # Must not raise or fail, even though no temp account exists
        response = viewset.end(request)

        # Verify the response is still successful
        assert response.status_code == 200

        # Verify the chat was marked as ended
        realtime_agent_chat.refresh_from_db()
        assert realtime_agent_chat.ended_at is not None
        assert realtime_agent_chat.duration_seconds == 60

    def test_realtime_agent_chat_viewset_end_missing_connection_key(self, viewset):
        """RealtimeAgentChatViewSet.end() requires connection_key in request"""
        factory = APIRequestFactory()
        django_request = factory.post(
            "/api/realtime-agent-chats/end/",
            data={
                "duration_seconds": 60,
                # connection_key intentionally omitted
            },
            format="json",
        )
        request = Request(django_request)

        response = viewset.end(request)

        # Should return 400 Bad Request
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_realtime_agent_chat_viewset_end_nonexistent_connection_key(self, viewset):
        """RealtimeAgentChatViewSet.end() returns 404 for nonexistent connection_key"""
        factory = APIRequestFactory()
        django_request = factory.post(
            "/api/realtime-agent-chats/end/",
            data={
                "connection_key": "nonexistent-connection-key",
                "duration_seconds": 60,
            },
            format="json",
        )
        request = Request(django_request)

        response = viewset.end(request)

        # Should return 404 Not Found
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @patch("storage_credentials.services.session_credential_service.StorageAdminGateway")
    def test_realtime_agent_chat_viewset_end_revocation_failure_logged(
        self, mock_gateway_class, viewset, realtime_agent_chat
    ):
        """When revocation fails, end() still marks the chat as ended (logged but not fatal)"""
        temp_account = TemporaryStorageAccount.objects.create(
            realtime_agent_chat=realtime_agent_chat,
            access_key="rt-temp-access-key",
        )

        # Mock the gateway to raise an error during revocation
        mock_gateway_instance = AsyncMock()
        mock_gateway_class.return_value = mock_gateway_instance
        mock_gateway_instance.delete_service_account = AsyncMock(
            side_effect=Exception("Gateway error")
        )
        mock_gateway_instance.close = AsyncMock()

        mock_org_creds = MagicMock()
        mock_org_creds.access_key = "org-access"
        mock_org_creds.secret_key = "org-secret"

        factory = APIRequestFactory()
        django_request = factory.post(
            "/api/realtime-agent-chats/end/",
            data={
                "connection_key": "conn-key-test-123",
                "duration_seconds": 100,
                "end_reason": "user_disconnected",
            },
            format="json",
        )
        request = Request(django_request)

        with patch(
            "storage_credentials.services.session_credential_service.org_credential_store.get",
            return_value=mock_org_creds,
        ):
            response = viewset.end(request)

        # Even though revocation failed, end() should return 200
        # (revocation failure is not fatal to chat termination)
        assert response.status_code == 200

        # Chat should still be marked as ended
        realtime_agent_chat.refresh_from_db()
        assert realtime_agent_chat.ended_at is not None

        # Revoke failed, so the opportunistic delete never ran -- the row is
        # deliberately left in place for the manager backstop job to find later.
        assert TemporaryStorageAccount.objects.filter(pk=temp_account.pk).exists()
