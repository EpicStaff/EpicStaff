"""Tests for TemporaryStorageAccount model CheckConstraint.

Verifies that exactly one of (session, python_code_result, realtime_agent_chat)
must be NOT NULL. Invalid combinations should raise IntegrityError.
"""

import pytest
from django.db import IntegrityError

from rbac.models import Organization
from storage_credentials.models import TemporaryStorageAccount
from tables.models import Graph, Session, PythonCodeResult, RealtimeAgentChat


@pytest.mark.django_db
class TestTemporaryStorageAccountConstraint:
    """Test cases for exactly_one_fk_is_not_null constraint."""

    @pytest.fixture
    def default_org(self, db):
        """Create a default organization for tests."""
        return Organization.objects.create(name="Test Organization")

    @pytest.fixture
    def graph(self, default_org):
        """Create a Graph for Session FK."""
        return Graph.objects.create(name="test_graph", org=default_org)

    @pytest.fixture
    def session(self, graph):
        """Create a Session for TemporaryStorageAccount.session FK."""
        return Session.objects.create(
            graph=graph,
            status=Session.SessionStatus.RUN,
        )

    @pytest.fixture
    def python_code_result(self, default_org):
        """Create a PythonCodeResult for TemporaryStorageAccount.python_code_result FK."""
        return PythonCodeResult.objects.create(
            org=default_org,
            execution_id="test_execution_123",
        )

    @pytest.fixture
    def realtime_agent_chat(self):
        """Create a RealtimeAgentChat for TemporaryStorageAccount.realtime_agent_chat FK."""
        return RealtimeAgentChat.objects.create(
            connection_key="test_connection_key",
        )

    def test_valid_with_session_only(self, session):
        """Should successfully save when only session is set (others NULL)."""
        account = TemporaryStorageAccount.objects.create(
            session=session,
            access_key="test-key-session-only",
        )
        assert account.id is not None
        assert account.session == session
        assert account.python_code_result is None
        assert account.realtime_agent_chat is None

    def test_valid_with_python_code_result_only(self, python_code_result):
        """Should successfully save when only python_code_result is set (others NULL)."""
        account = TemporaryStorageAccount.objects.create(
            python_code_result=python_code_result,
            access_key="test-key-python-result-only",
        )
        assert account.id is not None
        assert account.session is None
        assert account.python_code_result == python_code_result
        assert account.realtime_agent_chat is None

    def test_valid_with_realtime_agent_chat_only(self, realtime_agent_chat):
        """Should successfully save when only realtime_agent_chat is set (others NULL)."""
        account = TemporaryStorageAccount.objects.create(
            realtime_agent_chat=realtime_agent_chat,
            access_key="test-key-realtime-chat-only",
        )
        assert account.id is not None
        assert account.session is None
        assert account.python_code_result is None
        assert account.realtime_agent_chat == realtime_agent_chat

    def test_invalid_with_no_fk(self):
        """Should fail when all FK fields are NULL."""
        with pytest.raises(IntegrityError):
            TemporaryStorageAccount.objects.create(
                access_key="test-key-no-fk",
            )

    def test_invalid_with_session_and_python_code_result(
        self, session, python_code_result
    ):
        """Should fail when both session and python_code_result are set."""
        with pytest.raises(IntegrityError):
            TemporaryStorageAccount.objects.create(
                session=session,
                python_code_result=python_code_result,
                access_key="test-key-two-fks-1",
            )

    def test_invalid_with_session_and_realtime_agent_chat(
        self, session, realtime_agent_chat
    ):
        """Should fail when both session and realtime_agent_chat are set."""
        with pytest.raises(IntegrityError):
            TemporaryStorageAccount.objects.create(
                session=session,
                realtime_agent_chat=realtime_agent_chat,
                access_key="test-key-two-fks-2",
            )

    def test_invalid_with_python_code_result_and_realtime_agent_chat(
        self, python_code_result, realtime_agent_chat
    ):
        """Should fail when both python_code_result and realtime_agent_chat are set."""
        with pytest.raises(IntegrityError):
            TemporaryStorageAccount.objects.create(
                python_code_result=python_code_result,
                realtime_agent_chat=realtime_agent_chat,
                access_key="test-key-two-fks-3",
            )

    def test_invalid_with_all_three_fks(
        self, session, python_code_result, realtime_agent_chat
    ):
        """Should fail when all three FK fields are set."""
        with pytest.raises(IntegrityError):
            TemporaryStorageAccount.objects.create(
                session=session,
                python_code_result=python_code_result,
                realtime_agent_chat=realtime_agent_chat,
                access_key="test-key-all-fks",
            )
