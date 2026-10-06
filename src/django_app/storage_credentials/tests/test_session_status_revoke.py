"""Tests for session_status_handler credential revocation.

Tests the revocation and opportunistic deletion of temporary storage
credentials when a session reaches a terminal status.
"""

import json
from unittest import mock

from django.test import TestCase

from rbac.models import Organization
from storage_credentials.exceptions import TemporaryCredentialRevokeError
from storage_credentials.models import TemporaryStorageAccount
from tables.models import Session, Graph
from tables.services.redis_pubsub import RedisPubSub


class TestSessionStatusHandlerRevoke(TestCase):
    """Test revocation and opportunistic deletion of session storage credentials.

    Note: session_status_handler() uses transaction.on_commit(callback, robust=True)
    to defer credential revocation until after the outer transaction commits --
    this keeps the revoke network call from holding a database lock. Under
    django.test.TestCase, each test runs inside its own (always-rolled-back)
    outer transaction, so on_commit callbacks never fire on their own; every
    call to session_status_handler() below is wrapped in
    self.captureOnCommitCallbacks(execute=True) to force them to run.

    session_status_handler() also calls close_old_connections() for real --
    harmless in production, but under TestCase it closes the connection the
    test's own (always-rolled-back) transaction depends on. Mocked out here,
    mirroring the same pattern already used for code_results_handler() in
    test_run_code_storage_credentials.py.
    """

    def setUp(self):
        self.org = Organization.objects.create(name="Test Org")
        self.graph = Graph.objects.create(org=self.org, name="Test Graph")
        self.session = Session.objects.create(
            graph=self.graph, status=Session.SessionStatus.RUN
        )
        self.redis_pubsub = RedisPubSub()
        close_old_connections_patcher = mock.patch(
            "tables.services.redis_pubsub.close_old_connections"
        )
        close_old_connections_patcher.start()
        self.addCleanup(close_old_connections_patcher.stop)

    def test_session_status_handler_revokes_on_terminal_status_end(self):
        """Verify revoke and opportunistic delete on 'end' status."""
        temp_account = TemporaryStorageAccount.objects.create(
            session=self.session, access_key="test_access_key"
        )

        with mock.patch(
            "tables.services.redis_pubsub.session_credential_service.revoke"
        ) as mock_revoke:
            message = {
                "data": json.dumps(
                    {
                        "session_id": self.session.id,
                        "status": Session.SessionStatus.END,
                        "status_data": {"variables": {}},
                    }
                )
            }
            with self.captureOnCommitCallbacks(execute=True):
                self.redis_pubsub.session_status_handler(message)

            # Verify revoke was called with correct org_id from session.graph.org_id
            mock_revoke.assert_called_once_with(
                access_key="test_access_key", org_id=self.graph.org_id
            )

            # Verify row was deleted
            assert not TemporaryStorageAccount.objects.filter(id=temp_account.id).exists()

    def test_session_status_handler_revokes_on_terminal_status_error(self):
        """Verify revoke and opportunistic delete on 'error' status."""
        temp_account = TemporaryStorageAccount.objects.create(
            session=self.session, access_key="test_access_key"
        )

        with mock.patch(
            "tables.services.redis_pubsub.session_credential_service.revoke"
        ) as mock_revoke:
            message = {
                "data": json.dumps(
                    {
                        "session_id": self.session.id,
                        "status": Session.SessionStatus.ERROR,
                        "status_data": {},
                    }
                )
            }
            with self.captureOnCommitCallbacks(execute=True):
                self.redis_pubsub.session_status_handler(message)

            mock_revoke.assert_called_once_with(
                access_key="test_access_key", org_id=self.graph.org_id
            )
            assert not TemporaryStorageAccount.objects.filter(id=temp_account.id).exists()

    def test_session_status_handler_revokes_on_terminal_status_stop(self):
        """Verify revoke and opportunistic delete on 'stop' status."""
        temp_account = TemporaryStorageAccount.objects.create(
            session=self.session, access_key="test_access_key"
        )

        with mock.patch(
            "tables.services.redis_pubsub.session_credential_service.revoke"
        ) as mock_revoke:
            message = {
                "data": json.dumps(
                    {
                        "session_id": self.session.id,
                        "status": Session.SessionStatus.STOP,
                        "status_data": {},
                    }
                )
            }
            with self.captureOnCommitCallbacks(execute=True):
                self.redis_pubsub.session_status_handler(message)

            mock_revoke.assert_called_once_with(
                access_key="test_access_key", org_id=self.graph.org_id
            )
            assert not TemporaryStorageAccount.objects.filter(id=temp_account.id).exists()

    def test_session_status_handler_revokes_on_terminal_status_expired(self):
        """Verify revoke and opportunistic delete on 'expired' status."""
        temp_account = TemporaryStorageAccount.objects.create(
            session=self.session, access_key="test_access_key"
        )

        with mock.patch(
            "tables.services.redis_pubsub.session_credential_service.revoke"
        ) as mock_revoke:
            message = {
                "data": json.dumps(
                    {
                        "session_id": self.session.id,
                        "status": Session.SessionStatus.EXPIRED,
                        "status_data": {},
                    }
                )
            }
            with self.captureOnCommitCallbacks(execute=True):
                self.redis_pubsub.session_status_handler(message)

            mock_revoke.assert_called_once_with(
                access_key="test_access_key", org_id=self.graph.org_id
            )
            assert not TemporaryStorageAccount.objects.filter(id=temp_account.id).exists()

    def test_session_status_handler_revoke_failure_keeps_row(self):
        """Verify that failed revoke keeps the row in the database."""
        temp_account = TemporaryStorageAccount.objects.create(
            session=self.session, access_key="test_access_key"
        )

        with mock.patch(
            "tables.services.redis_pubsub.session_credential_service.revoke",
            side_effect=TemporaryCredentialRevokeError("Revoke failed"),
        ):
            message = {
                "data": json.dumps(
                    {
                        "session_id": self.session.id,
                        "status": Session.SessionStatus.ERROR,
                        "status_data": {},
                    }
                )
            }
            with self.captureOnCommitCallbacks(execute=True):
                self.redis_pubsub.session_status_handler(message)

            # Verify row was NOT deleted after revoke failure
            assert TemporaryStorageAccount.objects.filter(id=temp_account.id).exists()

    def test_session_status_handler_no_temp_account_no_op(self):
        """Verify no error when there's no temporary account for the session."""
        # Don't create any TemporaryStorageAccount for this session
        message = {
            "data": json.dumps(
                {
                    "session_id": self.session.id,
                    "status": Session.SessionStatus.END,
                    "status_data": {"variables": {}},
                }
            )
        }

        with mock.patch(
            "tables.services.redis_pubsub.session_credential_service.revoke"
        ) as mock_revoke:
            # Should not raise, should just log and return
            with self.captureOnCommitCallbacks(execute=True):
                self.redis_pubsub.session_status_handler(message)
            mock_revoke.assert_not_called()

    def test_session_status_handler_delete_row_failure_logs_but_continues(self):
        """Verify that deletion failure logs but doesn't block status update."""
        temp_account = TemporaryStorageAccount.objects.create(
            session=self.session, access_key="test_access_key"
        )

        with mock.patch(
            "tables.services.redis_pubsub.session_credential_service.revoke"
        ), mock.patch.object(
            TemporaryStorageAccount, "delete", side_effect=Exception("Delete failed")
        ):
            message = {
                "data": json.dumps(
                    {
                        "session_id": self.session.id,
                        "status": Session.SessionStatus.END,
                        "status_data": {"variables": {}},
                    }
                )
            }
            # Should not raise, should just log the error
            with self.captureOnCommitCallbacks(execute=True):
                self.redis_pubsub.session_status_handler(message)

            # Verify row still exists (delete failed)
            assert TemporaryStorageAccount.objects.filter(id=temp_account.id).exists()

            # Verify session status was updated despite delete failure
            self.session.refresh_from_db()
            assert self.session.status == Session.SessionStatus.END

    def test_session_status_handler_non_terminal_status_no_revoke(self):
        """Verify no revoke attempt for non-terminal statuses."""
        temp_account = TemporaryStorageAccount.objects.create(
            session=self.session, access_key="test_access_key"
        )

        with mock.patch(
            "tables.services.redis_pubsub.session_credential_service.revoke"
        ) as mock_revoke:
            message = {
                "data": json.dumps(
                    {
                        "session_id": self.session.id,
                        "status": Session.SessionStatus.RUN,
                        "status_data": {},
                    }
                )
            }
            with self.captureOnCommitCallbacks(execute=True):
                self.redis_pubsub.session_status_handler(message)

            # Revoke should not be called for non-terminal status
            mock_revoke.assert_not_called()

            # Row should still exist
            assert TemporaryStorageAccount.objects.filter(id=temp_account.id).exists()
