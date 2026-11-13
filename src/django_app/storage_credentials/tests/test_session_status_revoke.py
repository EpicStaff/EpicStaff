"""A session reaching a terminal status revokes its temporary storage credentials.

Revoking is a call to the storage server (MinIO), the external side effect, so the
storage gateway is the one thing replaced. The revoke runs in a
`transaction.on_commit` callback, hence `django_capture_on_commit_callbacks`.
"""

import json
from unittest import mock

import pytest

from rbac.models import Organization
from storage_credentials.models import TemporaryStorageAccount
from tables.models import Graph, Session
from tables.services.redis_pubsub import RedisPubSub

GATEWAY = "storage_credentials.services.session_credential_service.StorageAdminGateway"
ORG_CREDENTIALS = "storage_credentials.services.session_credential_service.org_credential_store.get"


@pytest.fixture
def gateway():
    instance = mock.AsyncMock()
    with mock.patch(GATEWAY, return_value=instance), mock.patch(ORG_CREDENTIALS):
        yield instance


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
    session, gateway, django_capture_on_commit_callbacks, status, revoked
):
    account = TemporaryStorageAccount.objects.create(session=session, access_key="test_access_key")

    _report_status(session, status, django_capture_on_commit_callbacks)

    if revoked:
        gateway.delete_service_account.assert_awaited_once_with("test_access_key")
    else:
        gateway.delete_service_account.assert_not_awaited()
    assert TemporaryStorageAccount.objects.filter(id=account.id).exists() is not revoked


@pytest.mark.parametrize("failure", ["revoke-fails", "row-delete-fails"])
def test_a_failed_cleanup_keeps_the_row_for_a_retry_and_still_ends_the_session(
    session, gateway, django_capture_on_commit_callbacks, failure
):
    account = TemporaryStorageAccount.objects.create(session=session, access_key="test_access_key")
    if failure == "revoke-fails":
        gateway.delete_service_account.side_effect = Exception("Revoke failed")
        _report_status(session, Session.SessionStatus.END, django_capture_on_commit_callbacks)
    else:
        with mock.patch(
            "django.db.models.query.QuerySet.delete", side_effect=Exception("Delete failed")
        ):
            _report_status(session, Session.SessionStatus.END, django_capture_on_commit_callbacks)

    assert TemporaryStorageAccount.objects.filter(id=account.id).exists()
    session.refresh_from_db()
    assert session.status == Session.SessionStatus.END


def test_a_session_without_credentials_revokes_nothing(
    session, gateway, django_capture_on_commit_callbacks
):
    _report_status(session, Session.SessionStatus.END, django_capture_on_commit_callbacks)

    gateway.delete_service_account.assert_not_awaited()


def test_several_accounts_are_revoked_on_one_gateway_and_only_confirmed_rows_go(
    session, django_capture_on_commit_callbacks
):
    accounts = {
        key: TemporaryStorageAccount.objects.create(session=session, access_key=key)
        for key in ("key-a", "key-b", "key-c")
    }
    instance = mock.AsyncMock()
    instance.delete_service_account.side_effect = [None, Exception("backend down"), None]

    with (
        mock.patch(GATEWAY, return_value=instance) as gateway_class,
        mock.patch(ORG_CREDENTIALS) as credentials_get,
    ):
        _report_status(session, Session.SessionStatus.END, django_capture_on_commit_callbacks)

    assert gateway_class.call_count == 1
    assert credentials_get.call_count == 1
    assert set(TemporaryStorageAccount.objects.values_list("access_key", flat=True)) == {"key-b"}
    assert TemporaryStorageAccount.objects.filter(pk=accounts["key-b"].pk).exists()
