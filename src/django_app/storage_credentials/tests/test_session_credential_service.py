"""Tests for session_credential_service.

Tests the issuance and persistence of temporary storage credentials for sessions.
"""

import asyncio
from datetime import timedelta
from unittest import mock

import pytest
from django.test import TestCase
from django.utils import timezone

from rbac.models import Organization
from src.shared.models.sessions import SessionData
from src.shared.models.graph_nodes import GraphData
from src.shared.models.storage_scope import StorageCredentials
from storage_credentials.models import TemporaryStorageAccount
from storage_credentials.services.session_credential_service import (
    issue_for_session,
    _mint_temporary_service_account,
)
from tables.models import Session, Graph


class TestIssueForSessionNoStorage(TestCase):
    """Test that sessions without storage requirements return None."""

    def setUp(self):
        self.org = Organization.objects.create(name="Test Org")
        self.graph = Graph.objects.create(org=self.org, name="Test Graph")
        self.session = Session.objects.create(graph=self.graph, organization=self.org)

    def test_issue_for_session_no_storage_returns_none(self):
        """Session without storage-demanding nodes should return None."""
        # Create minimal session data without any storage requirements
        session_data = SessionData(
            id=self.session.id,
            graph=GraphData(
                python_node_list=[],
                file_extractor_node_list=[],
                audio_transcription_node_list=[],
                classification_decision_table_node_list=[],
                agent_node_list=[],
                task_node_list=[],
                conditional_edge_list=[],
                edge_list=[],
                start_node=None,
                key_value_node_list=[],
                knowledge_node_list=[],
                knowledge_summary_node_list=[],
                subgraph_node_list=[],
                schedule_trigger_node_list=[],
                telegram_trigger_node_list=[],
                webhook_trigger_node_list=[],
            ),
        )

        result = issue_for_session(
            session_data=session_data, session_orm=self.session, org=self.org
        )

        assert result is None

    def test_no_temporary_account_created_when_not_needed(self):
        """Verify no TemporaryStorageAccount row is created for sessions without storage."""
        session_data = SessionData(
            id=self.session.id,
            graph=GraphData(
                python_node_list=[],
                file_extractor_node_list=[],
                audio_transcription_node_list=[],
                classification_decision_table_node_list=[],
                agent_node_list=[],
                task_node_list=[],
                conditional_edge_list=[],
                edge_list=[],
                start_node=None,
                key_value_node_list=[],
                knowledge_node_list=[],
                knowledge_summary_node_list=[],
                subgraph_node_list=[],
                schedule_trigger_node_list=[],
                telegram_trigger_node_list=[],
                webhook_trigger_node_list=[],
            ),
        )

        issue_for_session(
            session_data=session_data, session_orm=self.session, org=self.org
        )

        # Verify no row was created
        assert not TemporaryStorageAccount.objects.filter(session=self.session).exists()


class TestIssueForSessionWithStorage(TestCase):
    """Test that sessions with storage requirements mint and persist credentials."""

    def setUp(self):
        self.org = Organization.objects.create(name="Test Org")
        self.graph = Graph.objects.create(org=self.org, name="Test Graph")
        self.session = Session.objects.create(graph=self.graph, organization=self.org)

    @mock.patch("storage_credentials.services.session_credential_service.asyncio.run")
    @mock.patch("storage_credentials.services.session_credential_service.org_credential_store")
    def test_issue_for_session_mints_and_persists_credentials(
        self, mock_org_store, mock_asyncio_run
    ):
        """Verify credentials are minted and a TemporaryStorageAccount row is created."""
        from src.shared.models.graph_nodes import PythonNodeData

        # Mock the async mint call
        mock_access_key = "test_access_key_123"
        mock_secret_key = "test_secret_key_456"
        mock_asyncio_run.return_value = (mock_access_key, mock_secret_key)

        # Mock org credentials
        mock_org_creds = mock.MagicMock()
        mock_org_creds.access_key = "org_access_key"
        mock_org_creds.secret_key = "org_secret_key"
        mock_org_store.get.return_value = mock_org_creds

        # Create session data with a storage-demanding node
        python_data = PythonNodeData(
            id="python_1",
            name="Storage Python",
            python_code="x = 1",
            use_storage=True,
            storage_allowed_paths=["test_path/"],
            storage_org_prefix="org_123",
            org_id=self.org.id,
        )
        session_data = SessionData(
            id=self.session.id,
            graph=GraphData(
                python_node_list=[
                    mock.MagicMock(python_code=python_data, id="node_1", name="Test Node")
                ],
                file_extractor_node_list=[],
                audio_transcription_node_list=[],
                classification_decision_table_node_list=[],
                agent_node_list=[],
                task_node_list=[],
                conditional_edge_list=[],
                edge_list=[],
                start_node=None,
                key_value_node_list=[],
                knowledge_node_list=[],
                knowledge_summary_node_list=[],
                subgraph_node_list=[],
                schedule_trigger_node_list=[],
                telegram_trigger_node_list=[],
                webhook_trigger_node_list=[],
            ),
        )

        result = issue_for_session(
            session_data=session_data, session_orm=self.session, org=self.org
        )

        # Verify credentials were returned
        assert result is not None
        assert isinstance(result, StorageCredentials)
        assert result.access_key == mock_access_key
        assert result.secret_key == mock_secret_key

        # Verify TemporaryStorageAccount was created
        temp_account = TemporaryStorageAccount.objects.get(session=self.session)
        assert temp_account.access_key == mock_access_key
        assert temp_account.issued_at is not None

    @mock.patch("storage_credentials.services.session_credential_service.asyncio.run")
    @mock.patch("storage_credentials.services.session_credential_service.org_credential_store")
    def test_db_write_failure_raises_exception(self, mock_org_store, mock_asyncio_run):
        """Verify that DB write failure propagates as an exception."""
        from src.shared.models.graph_nodes import PythonNodeData

        # Mock the async mint call
        mock_asyncio_run.return_value = ("test_access", "test_secret")

        # Mock org credentials
        mock_org_creds = mock.MagicMock()
        mock_org_creds.access_key = "org_access_key"
        mock_org_creds.secret_key = "org_secret_key"
        mock_org_store.get.return_value = mock_org_creds

        # Create session data with storage requirement
        python_data = PythonNodeData(
            id="python_1",
            name="Storage Python",
            python_code="x = 1",
            use_storage=True,
            storage_allowed_paths=["test_path/"],
            storage_org_prefix="org_123",
            org_id=self.org.id,
        )
        session_data = SessionData(
            id=self.session.id,
            graph=GraphData(
                python_node_list=[
                    mock.MagicMock(python_code=python_data, id="node_1", name="Test Node")
                ],
                file_extractor_node_list=[],
                audio_transcription_node_list=[],
                classification_decision_table_node_list=[],
                agent_node_list=[],
                task_node_list=[],
                conditional_edge_list=[],
                edge_list=[],
                start_node=None,
                key_value_node_list=[],
                knowledge_node_list=[],
                knowledge_summary_node_list=[],
                subgraph_node_list=[],
                schedule_trigger_node_list=[],
                telegram_trigger_node_list=[],
                webhook_trigger_node_list=[],
            ),
        )

        # Mock DB write failure
        with mock.patch(
            "storage_credentials.models.TemporaryStorageAccount.objects.create",
            side_effect=Exception("DB write failed"),
        ):
            with pytest.raises(Exception, match="Failed to persist temporary storage account"):
                issue_for_session(
                    session_data=session_data, session_orm=self.session, org=self.org
                )

    @mock.patch("storage_credentials.services.session_credential_service.asyncio.run")
    def test_repeated_calls_in_same_process_no_event_loop_error(self, mock_asyncio_run):
        """Verify that repeated calls in the same process don't fail with event loop errors.

        Each call should use asyncio.run() to create a new isolated event loop,
        preventing "Event loop is closed" or "Event loop already running" errors.
        """
        from src.shared.models.graph_nodes import PythonNodeData

        # Mock the async mint call to succeed
        mock_asyncio_run.return_value = ("access1", "secret1")

        python_data = PythonNodeData(
            id="python_1",
            name="Storage Python",
            python_code="x = 1",
            use_storage=True,
            storage_allowed_paths=["test_path/"],
            storage_org_prefix="org_123",
            org_id=self.org.id,
        )

        def create_session_data(session_id):
            return SessionData(
                id=session_id,
                graph=GraphData(
                    python_node_list=[
                        mock.MagicMock(python_code=python_data, id="node_1", name="Test Node")
                    ],
                    file_extractor_node_list=[],
                    audio_transcription_node_list=[],
                    classification_decision_table_node_list=[],
                    agent_node_list=[],
                    task_node_list=[],
                    conditional_edge_list=[],
                    edge_list=[],
                    start_node=None,
                    key_value_node_list=[],
                    knowledge_node_list=[],
                    knowledge_summary_node_list=[],
                    subgraph_node_list=[],
                    schedule_trigger_node_list=[],
                    telegram_trigger_node_list=[],
                    webhook_trigger_node_list=[],
                ),
            )

        # Create two sessions
        session2 = Session.objects.create(graph=self.graph, organization=self.org)

        # Mock org credentials for both calls
        with mock.patch(
            "storage_credentials.services.session_credential_service.org_credential_store"
        ) as mock_org_store:
            mock_org_creds = mock.MagicMock()
            mock_org_creds.access_key = "org_access_key"
            mock_org_creds.secret_key = "org_secret_key"
            mock_org_store.get.return_value = mock_org_creds

            # First call should succeed
            result1 = issue_for_session(
                session_data=create_session_data(self.session.id),
                session_orm=self.session,
                org=self.org,
            )
            assert result1 is not None

            # Second call should also succeed (no event loop error)
            result2 = issue_for_session(
                session_data=create_session_data(session2.id),
                session_orm=session2,
                org=self.org,
            )
            assert result2 is not None

            # Verify asyncio.run was called twice
            assert mock_asyncio_run.call_count == 2
