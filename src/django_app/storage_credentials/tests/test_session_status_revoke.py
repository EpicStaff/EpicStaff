"""A session reaching a terminal status revokes its temporary storage credentials.

Revoking is a call to the storage server (MinIO), the external side effect, so
`session_credential_service.revoke` is the one thing replaced. The revoke runs in a
`transaction.on_commit` callback, hence `django_capture_on_commit_callbacks`.
"""

import json
from contextlib import nullcontext
from unittest import mock

import pytest

from rbac.models import Organization
from storage_credentials.exceptions import TemporaryCredentialRevokeError
from storage_credentials.models import TemporaryStorageAccount
from tables.models import Graph, Session
from tables.services.redis_pubsub import RedisPubSub

REVOKE = "tables.services.redis_pubsub.session_credential_service.revoke"


@pytest.fixture
def session(db, monkeypatch):
    # The handler calls close_old_connections(), which would close the test's own transaction.
    monkeypatch.setattr("tables.services.redis_pubsub.close_old_connections", lambda: None)
    graph = Graph.objects.create(org=Organization.objects.create(name="Test Org"), name="Test Graph")
    return Session.objects.create(graph=graph, status=Session.SessionStatus.RUN)


def _report_status(session, status, capture):
    message = {"data": json.dumps({"session_id": session.id, "status": status, "status_data": {"variables": {}}})}
    with capture(execute=True):
        RedisPubSub().session_status_handler(message)


@pytest.mark.parametrize(
    ("status", "revoked"),
    [
        (Session.SessionStatus.END, True),
        (Session.SessionStatus.ERROR, True),
        (Session.SessionStatus.STOP, True),
        (Session.SessionStatus.EXPIRED, True),
        (Session.SessionStatus.RUN, False),
    ],
)
def test_terminal_status_revokes_the_sessions_credentials_and_drops_the_row(
    session, django_capture_on_commit_callbacks, status, revoked
):
    account = TemporaryStorageAccount.objects.create(session=session, access_key="test_access_key")

    with mock.patch(REVOKE) as revoke:
        _report_status(session, status, django_capture_on_commit_callbacks)

    if revoked:
        revoke.assert_called_once_with(access_key="test_access_key", org_id=session.graph.org_id)
    else:
        revoke.assert_not_called()
    assert TemporaryStorageAccount.objects.filter(id=account.id).exists() is not revoked


@pytest.mark.parametrize(
    ("revoke_error", "delete_error"),
    [(TemporaryCredentialRevokeError("Revoke failed"), None), (None, Exception("Delete failed"))],
    ids=["revoke-fails", "row-delete-fails"],
)
def test_a_failed_cleanup_keeps_the_row_for_a_retry_and_still_ends_the_session(
    session, django_capture_on_commit_callbacks, revoke_error, delete_error
):
    account = TemporaryStorageAccount.objects.create(session=session, access_key="test_access_key")

    failing_delete = (
        mock.patch.object(TemporaryStorageAccount, "delete", side_effect=delete_error)
        if delete_error
        else nullcontext()
    )
    with mock.patch(REVOKE, side_effect=revoke_error), failing_delete:
        _report_status(session, Session.SessionStatus.END, django_capture_on_commit_callbacks)

    assert TemporaryStorageAccount.objects.filter(id=account.id).exists()
    session.refresh_from_db()
    assert session.status == Session.SessionStatus.END


def test_a_session_without_credentials_revokes_nothing(session, django_capture_on_commit_callbacks):
    with mock.patch(REVOKE) as revoke:
        _report_status(session, Session.SessionStatus.END, django_capture_on_commit_callbacks)

    revoke.assert_not_called()
