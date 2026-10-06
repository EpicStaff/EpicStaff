"""Tests for session_credential_service.

Tests the issuance and persistence of temporary storage credentials for sessions.
"""

from unittest import mock

import pytest
from django.test import TestCase

from django.conf import settings

from rbac.models import Organization
from src.shared.models.graph_nodes import EndNodeData, GraphData, PythonNodeData
from src.shared.models.sessions import SessionData
from src.shared.models.storage_scope import StorageCredentials
from src.shared.models.tools import PythonCodeData
from storage_credentials.models import TemporaryStorageAccount
from storage_credentials.services.session_credential_service import issue_for_session
from tables.models import Graph, Session


def _make_graph(python_node_list: list[PythonNodeData] | None = None) -> GraphData:
    """A minimal valid GraphData, optionally carrying python nodes."""
    return GraphData(
        graph_id=1,
        name="test_graph",
        entrypoint="start",
        end_node=EndNodeData(node_name="end", output_map={}),
        python_node_list=python_node_list or [],
    )


def _make_storage_python_node(
    node_name: str = "storage_python",
    storage_allowed_paths: list[str] | None = None,
    storage_org_prefix: str = "org_123",
    org_id: int | None = None,
) -> PythonNodeData:
    """A python node whose code demands storage access."""
    return PythonNodeData(
        node_name=node_name,
        python_code=PythonCodeData(
            venv_name="test",
            code="x = 1",
            entrypoint="main",
            libraries=[],
            use_storage=True,
            storage_allowed_paths=storage_allowed_paths or ["test_path/"],
            storage_org_prefix=storage_org_prefix,
            org_id=org_id,
        ),
        input_map={},
    )


def _make_session_data(session_id: int, graph: GraphData) -> SessionData:
    return SessionData(id=session_id, graph=graph, unique_subgraph_list=[])


def _asyncio_run_stub(*credentials: tuple[str, str]):
    """Stand in for asyncio.run: close the coroutine it is handed and return the
    next (access_key, secret_key) pair, so no coroutine is left un-awaited.

    One pair per expected call -- TemporaryStorageAccount.access_key is unique,
    so consecutive calls must mint distinct keys.
    """
    remaining = iter(credentials)

    def run(coroutine):
        coroutine.close()
        return next(remaining)

    return run


class TestIssueForSessionNoStorage(TestCase):
    """Test that sessions without storage requirements return None."""

    def setUp(self):
        self.org = Organization.objects.create(name="Test Org")
        self.graph = Graph.objects.create(org=self.org, name="Test Graph")
        self.session = Session.objects.create(
            graph=self.graph, status=Session.SessionStatus.PENDING
        )

    def test_issue_for_session_no_storage_returns_none(self):
        """Session without storage-demanding nodes should return None."""
        session_data = _make_session_data(self.session.id, _make_graph())

        result = issue_for_session(
            session_data=session_data, session_orm=self.session, org=self.org
        )

        assert result is None

    def test_no_temporary_account_created_when_not_needed(self):
        """Verify no TemporaryStorageAccount row is created for sessions without storage."""
        session_data = _make_session_data(self.session.id, _make_graph())

        issue_for_session(session_data=session_data, session_orm=self.session, org=self.org)

        assert not TemporaryStorageAccount.objects.filter(session=self.session).exists()


class TestIssueForSessionWithStorage(TestCase):
    """Test that sessions with storage requirements mint and persist credentials."""

    def setUp(self):
        self.org = Organization.objects.create(name="Test Org")
        self.graph = Graph.objects.create(org=self.org, name="Test Graph")
        self.session = Session.objects.create(
            graph=self.graph, status=Session.SessionStatus.PENDING
        )

    def _storage_session_data(self, session_id: int) -> SessionData:
        return _make_session_data(
            session_id,
            _make_graph([_make_storage_python_node(org_id=self.org.id)]),
        )

    @staticmethod
    def _stub_org_credentials(mock_org_store) -> None:
        org_creds = mock.MagicMock()
        org_creds.access_key = "org_access_key"
        org_creds.secret_key = "org_secret_key"
        mock_org_store.get.return_value = org_creds

    @mock.patch("storage_credentials.services.session_credential_service.asyncio.run")
    @mock.patch("storage_credentials.services.session_credential_service.org_credential_store")
    def test_issue_for_session_mints_and_persists_credentials(
        self, mock_org_store, mock_asyncio_run
    ):
        """Verify credentials are minted and a TemporaryStorageAccount row is created."""
        minted_access_key = "test_access_key_123"
        minted_secret_key = "test_secret_key_456"
        mock_asyncio_run.side_effect = _asyncio_run_stub(
            (minted_access_key, minted_secret_key)
        )
        self._stub_org_credentials(mock_org_store)

        result = issue_for_session(
            session_data=self._storage_session_data(self.session.id),
            session_orm=self.session,
            org=self.org,
        )

        assert result is not None
        assert isinstance(result, StorageCredentials)
        assert result.access_key == minted_access_key
        assert result.secret_key == minted_secret_key

        temp_account = TemporaryStorageAccount.objects.get(session=self.session)
        assert temp_account.access_key == minted_access_key
        assert temp_account.issued_at is not None

    @mock.patch("storage_credentials.services.session_credential_service.build_temporary_policy")
    @mock.patch("storage_credentials.services.session_credential_service.asyncio.run")
    @mock.patch("storage_credentials.services.session_credential_service.org_credential_store")
    def test_issue_for_session_uses_union_of_allowed_paths_across_nodes(
        self, mock_org_store, mock_asyncio_run, mock_build_policy
    ):
        """Scope policy must cover the union of allowed_paths across every
        storage-demanding node, not just the first/last one seen."""
        mock_asyncio_run.side_effect = _asyncio_run_stub(("test_access", "test_secret"))
        self._stub_org_credentials(mock_org_store)
        mock_build_policy.return_value = {}

        graph = _make_graph(
            [
                _make_storage_python_node(
                    node_name="node_a",
                    storage_allowed_paths=["path_a/"],
                    org_id=self.org.id,
                ),
                _make_storage_python_node(
                    node_name="node_b",
                    storage_allowed_paths=["path_b/"],
                    org_id=self.org.id,
                ),
            ]
        )
        session_data = _make_session_data(self.session.id, graph)

        issue_for_session(session_data=session_data, session_orm=self.session, org=self.org)

        mock_build_policy.assert_called_once_with(
            bucket=settings.STORAGE_BUCKET_NAME, allowed_folders={"path_a/", "path_b/"}
        )

    @mock.patch("storage_credentials.services.session_credential_service.asyncio.run")
    @mock.patch("storage_credentials.services.session_credential_service.org_credential_store")
    def test_db_write_failure_raises_exception(self, mock_org_store, mock_asyncio_run):
        """Verify that DB write failure propagates as an exception."""
        mock_asyncio_run.side_effect = _asyncio_run_stub(("test_access", "test_secret"))
        self._stub_org_credentials(mock_org_store)

        session_data = self._storage_session_data(self.session.id)

        with mock.patch(
            "storage_credentials.models.TemporaryStorageAccount.objects.create",
            side_effect=Exception("DB write failed"),
        ):
            with pytest.raises(Exception, match="Failed to persist temporary storage account"):
                issue_for_session(
                    session_data=session_data, session_orm=self.session, org=self.org
                )

    @mock.patch("storage_credentials.services.session_credential_service.StorageAdminGateway")
    def test_repeated_calls_in_same_process_no_event_loop_error(self, mock_gateway_class):
        """Verify that repeated calls in the same process don't fail with event loop errors.

        asyncio.run() is NOT mocked here -- it runs for real, twice, each
        creating and closing its own event loop. Only the storage backend
        (StorageAdminGateway) is mocked. This is what actually exercises the
        regression this test is named for: OrgCredentialCache used to cache an
        asyncio.Lock/aiohttp session tied to the first call's event loop, and
        raised "Event loop is closed" on the second asyncio.run() in the same
        process. A fully-mocked asyncio.run can never observe that failure
        mode, since no real event loop is ever created or closed.
        """
        credentials = iter(
            [("access1", "secret1"), ("access2", "secret2")]
        )

        def make_gateway_instance(**kwargs):
            instance = mock.AsyncMock()
            instance.create_service_account.return_value = next(credentials)
            return instance

        mock_gateway_class.side_effect = make_gateway_instance

        second_session = Session.objects.create(
            graph=self.graph, status=Session.SessionStatus.PENDING
        )

        with mock.patch(
            "storage_credentials.services.session_credential_service.org_credential_store"
        ) as mock_org_store:
            self._stub_org_credentials(mock_org_store)

            first_result = issue_for_session(
                session_data=self._storage_session_data(self.session.id),
                session_orm=self.session,
                org=self.org,
            )
            assert first_result is not None
            assert first_result.access_key == "access1"

            second_result = issue_for_session(
                session_data=self._storage_session_data(second_session.id),
                session_orm=second_session,
                org=self.org,
            )
            assert second_result is not None
            assert second_result.access_key == "access2"

            assert mock_gateway_class.call_count == 2
