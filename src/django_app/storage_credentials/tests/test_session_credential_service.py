"""Tests for session_credential_service.

Tests the issuance and persistence of temporary storage credentials for sessions.
"""

from datetime import timedelta
from unittest import mock

import pytest
from django.test import TestCase, override_settings

from django.conf import settings

from rbac.models import Organization
from src.shared.models.graph_nodes import EndNodeData, GraphData, PythonNodeData
from src.shared.models.sessions import SessionData
from src.shared.models.storage_scope import StorageCredentials
from src.shared.models.tools import PythonCodeData
from storage_credentials.exceptions import (
    CredentialScopeValidationError,
    TemporaryCredentialIssueError,
)
from storage_credentials.models import TemporaryStorageAccount
from storage_credentials.services.session_credential_service import session_credential_service
from tables.models import Graph, PythonCodeResult, RealtimeAgentChat, Session


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


def _stub_gateway(mock_gateway_class, access_key: str = "minted_key") -> mock.AsyncMock:
    """Make the patched StorageAdminGateway class hand back one AsyncMock whose
    `create_service_account` call can be inspected. `asyncio.run` is left alone
    so the real coroutine executes and the real policy dict reaches the mock."""
    instance = mock.AsyncMock()
    instance.create_service_account.return_value = (access_key, f"{access_key}_secret")
    mock_gateway_class.return_value = instance
    return instance


def _minted_policy(gateway: mock.AsyncMock) -> dict:
    gateway.create_service_account.assert_awaited_once()
    return gateway.create_service_account.await_args.kwargs["policy"]


def _minted_expiration(gateway: mock.AsyncMock) -> timedelta | None:
    gateway.create_service_account.assert_awaited_once()
    return gateway.create_service_account.await_args.kwargs["expiration"]


def _object_resources(policy: dict) -> list[str]:
    """Resources of the policy statement granting object-level S3 access."""
    return [
        resource
        for statement in policy["Statement"]
        if statement["Effect"] == "Allow" and "s3:GetObject" in statement["Action"]
        for resource in statement["Resource"]
    ]


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

        result = session_credential_service.issue_for_session(
            session_data=session_data, session_orm=self.session, org=self.org
        )

        assert result is None

    def test_no_temporary_account_created_when_not_needed(self):
        """Verify no TemporaryStorageAccount row is created for sessions without storage."""
        session_data = _make_session_data(self.session.id, _make_graph())

        session_credential_service.issue_for_session(session_data=session_data, session_orm=self.session, org=self.org)

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

        result = session_credential_service.issue_for_session(
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
        storage-demanding node, not just the first/last one seen -- each one
        namespaced under the minting org's prefix."""
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

        session_credential_service.issue_for_session(session_data=session_data, session_orm=self.session, org=self.org)

        mock_build_policy.assert_called_once_with(
            bucket=settings.STORAGE_BUCKET_NAME,
            allowed_folders={
                f"org_{self.org.id}/path_a/",
                f"org_{self.org.id}/path_b/",
            },
        )

    @mock.patch("storage_credentials.services.session_credential_service.asyncio.run")
    @mock.patch("storage_credentials.services.session_credential_service.org_credential_store")
    def test_db_write_failure_raises_exception(self, mock_org_store, mock_asyncio_run):
        """A DB write failure must surface as the domain exception, and the
        raw DB error text must stay out of the client-facing detail -- DRF
        renders `detail` verbatim, and an IntegrityError can embed the
        access_key value."""
        mock_asyncio_run.side_effect = _asyncio_run_stub(("test_access", "test_secret"))
        self._stub_org_credentials(mock_org_store)

        session_data = self._storage_session_data(self.session.id)

        with mock.patch(
            "storage_credentials.models.TemporaryStorageAccount.objects.create",
            side_effect=Exception("DB write failed: Key (access_key)=(test_access) already exists"),
        ):
            with pytest.raises(TemporaryCredentialIssueError) as exc_info:
                session_credential_service.issue_for_session(
                    session_data=session_data, session_orm=self.session, org=self.org
                )

        detail = str(exc_info.value)
        assert detail == TemporaryCredentialIssueError.default_detail
        assert "DB write failed" not in detail
        assert "test_access" not in detail

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

            first_result = session_credential_service.issue_for_session(
                session_data=self._storage_session_data(self.session.id),
                session_orm=self.session,
                org=self.org,
            )
            assert first_result is not None
            assert first_result.access_key == "access1"

            second_result = session_credential_service.issue_for_session(
                session_data=self._storage_session_data(second_session.id),
                session_orm=second_session,
                org=self.org,
            )
            assert second_result is not None
            assert second_result.access_key == "access2"

            assert mock_gateway_class.call_count == 2


@mock.patch("storage_credentials.services.session_credential_service.org_credential_store")
@mock.patch("storage_credentials.services.session_credential_service.StorageAdminGateway")
class TestMintedPolicyIsOrgPrefixed(TestCase):
    """Every path must scope the minted account under the prefix of the org
    whose credentials do the minting -- never under a prefix carried by the
    graph/tool data, which an attacker controlling a node could point at
    another organization."""

    def setUp(self):
        self.org = Organization.objects.create(name="Minting Org")
        self.graph = Graph.objects.create(org=self.org, name="Test Graph")
        self.session = Session.objects.create(
            graph=self.graph, status=Session.SessionStatus.PENDING
        )

    @staticmethod
    def _stub_org_credentials(mock_org_store) -> None:
        org_creds = mock.MagicMock()
        org_creds.access_key = "org_access_key"
        org_creds.secret_key = "org_secret_key"
        mock_org_store.get.return_value = org_creds

    def test_session_policy_is_scoped_under_minting_org_prefix(
        self, mock_gateway_class, mock_org_store
    ):
        self._stub_org_credentials(mock_org_store)
        gateway = _stub_gateway(mock_gateway_class, "session_key")

        session_data = _make_session_data(
            self.session.id,
            _make_graph(
                [
                    _make_storage_python_node(
                        storage_allowed_paths=["flow_files/"], org_id=self.org.id
                    )
                ]
            ),
        )

        session_credential_service.issue_for_session(session_data=session_data, session_orm=self.session, org=self.org)

        assert _object_resources(_minted_policy(gateway)) == [
            f"arn:aws:s3:::{settings.STORAGE_BUCKET_NAME}/org_{self.org.id}/flow_files/*"
        ]

    def test_session_policy_ignores_node_declared_org_prefix_of_another_org(
        self, mock_gateway_class, mock_org_store
    ):
        """A node claiming `storage_org_prefix="org_999"` must not widen the
        minted account beyond the minting org's own prefix."""
        self._stub_org_credentials(mock_org_store)
        gateway = _stub_gateway(mock_gateway_class, "hostile_prefix_key")

        session_data = _make_session_data(
            self.session.id,
            _make_graph(
                [
                    _make_storage_python_node(
                        storage_allowed_paths=["victim_files/"],
                        storage_org_prefix="org_999",
                        org_id=self.org.id,
                    )
                ]
            ),
        )

        session_credential_service.issue_for_session(session_data=session_data, session_orm=self.session, org=self.org)

        resources = _object_resources(_minted_policy(gateway))
        assert resources == [
            f"arn:aws:s3:::{settings.STORAGE_BUCKET_NAME}/org_{self.org.id}/victim_files/*"
        ]
        assert not any("org_999" in resource for resource in resources)

    def test_test_run_policy_is_scoped_under_minting_org_prefix(
        self, mock_gateway_class, mock_org_store
    ):
        self._stub_org_credentials(mock_org_store)
        gateway = _stub_gateway(mock_gateway_class, "test_run_key")
        python_code_result = PythonCodeResult.objects.create(
            execution_id="exec-org-prefix", org=self.org
        )

        credentials = session_credential_service.issue_for_test_run(
            python_code_result=python_code_result,
            storage_allowed_paths=["test-runs/exec-org-prefix/"],
            org_id=self.org.id,
        )

        assert credentials.access_key == "test_run_key"
        assert _object_resources(_minted_policy(gateway)) == [
            f"arn:aws:s3:::{settings.STORAGE_BUCKET_NAME}"
            f"/org_{self.org.id}/test-runs/exec-org-prefix/*"
        ]
        assert TemporaryStorageAccount.objects.filter(
            python_code_result=python_code_result, access_key="test_run_key"
        ).exists()

    def test_realtime_chat_policy_is_scoped_under_minting_org_prefix(
        self, mock_gateway_class, mock_org_store
    ):
        self._stub_org_credentials(mock_org_store)
        gateway = _stub_gateway(mock_gateway_class, "realtime_key")
        chat = RealtimeAgentChat.objects.create(connection_key="conn-org-prefix")

        credentials = session_credential_service.issue_for_realtime_chat(
            realtime_agent_chat=chat,
            storage_allowed_paths=["shared/notes.txt"],
            org_id=self.org.id,
        )

        assert credentials.access_key == "realtime_key"
        assert _object_resources(_minted_policy(gateway)) == [
            f"arn:aws:s3:::{settings.STORAGE_BUCKET_NAME}/org_{self.org.id}/shared/notes.txt"
        ]
        assert TemporaryStorageAccount.objects.filter(
            realtime_agent_chat=chat, access_key="realtime_key"
        ).exists()


@mock.patch("storage_credentials.services.session_credential_service.org_credential_store")
@mock.patch("storage_credentials.services.session_credential_service.StorageAdminGateway")
class TestTemporaryCredentialExpiration(TestCase):
    """`STORAGE_TEMP_CREDENTIALS_TTL_HOURS <= 0` means "no expiration", which
    the storage backend expresses as an omitted `expiration` field -- not as a
    ~100-year timedelta, which the backend rejects outright."""

    def setUp(self):
        self.org = Organization.objects.create(name="TTL Org")
        self.python_code_result = PythonCodeResult.objects.create(
            execution_id="exec-ttl", org=self.org
        )

    @staticmethod
    def _stub_org_credentials(mock_org_store) -> None:
        org_creds = mock.MagicMock()
        org_creds.access_key = "org_access_key"
        org_creds.secret_key = "org_secret_key"
        mock_org_store.get.return_value = org_creds

    def _issue(self) -> None:
        session_credential_service.issue_for_test_run(
            python_code_result=self.python_code_result,
            storage_allowed_paths=["test-runs/exec-ttl/"],
            org_id=self.org.id,
        )

    @override_settings(STORAGE_TEMP_CREDENTIALS_TTL_HOURS=0)
    def test_zero_ttl_mints_without_expiration(self, mock_gateway_class, mock_org_store):
        self._stub_org_credentials(mock_org_store)
        gateway = _stub_gateway(mock_gateway_class, "no_expiry_key")

        self._issue()

        assert _minted_expiration(gateway) is None

    @override_settings(STORAGE_TEMP_CREDENTIALS_TTL_HOURS=-1)
    def test_negative_ttl_mints_without_expiration(self, mock_gateway_class, mock_org_store):
        self._stub_org_credentials(mock_org_store)
        gateway = _stub_gateway(mock_gateway_class, "negative_ttl_key")

        self._issue()

        assert _minted_expiration(gateway) is None

    @override_settings(STORAGE_TEMP_CREDENTIALS_TTL_HOURS=6)
    def test_positive_ttl_mints_with_that_lifetime(self, mock_gateway_class, mock_org_store):
        self._stub_org_credentials(mock_org_store)
        gateway = _stub_gateway(mock_gateway_class, "six_hour_key")

        self._issue()

        assert _minted_expiration(gateway) == timedelta(hours=6)


@mock.patch("storage_credentials.services.session_credential_service.org_credential_store")
@mock.patch("storage_credentials.services.session_credential_service.StorageAdminGateway")
class TestScopeValidationRejectsBadPaths(TestCase):
    """A path that escapes the org prefix, or no path at all, must stop the
    mint before the storage backend is contacted and before any
    TemporaryStorageAccount row exists."""

    def setUp(self):
        self.org = Organization.objects.create(name="Scope Org")
        self.python_code_result = PythonCodeResult.objects.create(
            execution_id="exec-scope", org=self.org
        )

    def _issue(self, storage_allowed_paths: list[str]) -> None:
        session_credential_service.issue_for_test_run(
            python_code_result=self.python_code_result,
            storage_allowed_paths=storage_allowed_paths,
            org_id=self.org.id,
        )

    def test_parent_traversal_path_is_rejected(self, mock_gateway_class, mock_org_store):
        with pytest.raises(CredentialScopeValidationError, match="Path traversal"):
            self._issue(["../org_999/secrets/"])

        mock_gateway_class.assert_not_called()
        assert not TemporaryStorageAccount.objects.filter(
            python_code_result=self.python_code_result
        ).exists()

    def test_nested_traversal_segment_is_rejected(self, mock_gateway_class, mock_org_store):
        with pytest.raises(CredentialScopeValidationError, match="Path traversal"):
            self._issue(["reports/../../org_999/"])

        mock_gateway_class.assert_not_called()

    def test_empty_allowed_paths_is_rejected(self, mock_gateway_class, mock_org_store):
        with pytest.raises(CredentialScopeValidationError, match="refusing to scope"):
            self._issue([])

        mock_gateway_class.assert_not_called()
        assert not TemporaryStorageAccount.objects.filter(
            python_code_result=self.python_code_result
        ).exists()

    def test_blank_path_entry_is_rejected(self, mock_gateway_class, mock_org_store):
        with pytest.raises(CredentialScopeValidationError, match="empty path"):
            self._issue(["   "])

        mock_gateway_class.assert_not_called()

    def test_absolute_path_is_confined_to_the_org_prefix(
        self, mock_gateway_class, mock_org_store
    ):
        """A leading "/" must not produce a bucket-root resource: the
        validator strips it and the path stays under the org prefix."""
        org_creds = mock.MagicMock()
        org_creds.access_key = "org_access_key"
        org_creds.secret_key = "org_secret_key"
        mock_org_store.get.return_value = org_creds
        gateway = _stub_gateway(mock_gateway_class, "absolute_path_key")

        self._issue(["/escaped/"])

        assert _object_resources(_minted_policy(gateway)) == [
            f"arn:aws:s3:::{settings.STORAGE_BUCKET_NAME}/org_{self.org.id}/escaped/*"
        ]
