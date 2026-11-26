"""Multipart uploads a run started and never completed are aborted when its account is revoked.

Their parts take space no object, listing or notification shows, so they would stay stored and
uncounted. Only the run's own folders are cleared: the store does not say who started an
upload, and one in a shared folder may be the app's own upload in progress.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from src.shared.models.storage_scope import StorageAction
from storage_credentials.services import session_credential_service as service_module
from storage_credentials.services.session_credential_service import session_credential_service
from tables.models import Graph, PythonCodeResult, Session

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.services_tests.test_run_code_storage_credentials import (
    GATEWAY_PATH,
    ORG_CREDENTIALS_PATH,
    FakeStorageGateway,
)
from tests.services_tests.test_storage_grant_accounts import _issue
from tests.storage_tests.in_memory_backend import FakeS3Client, InMemoryStorageBackend, make_s3_backend


@pytest.fixture(autouse=True)
def _storage_settings(settings):
    settings.STORAGE_BUCKET_NAME = "bucket"
    settings.ORG_STORAGE_QUOTA = 10**9


@pytest.fixture
def backend(monkeypatch):
    in_memory = InMemoryStorageBackend(organization_prefix="")
    monkeypatch.setattr(service_module, "get_storage_backend", lambda organization_prefix="": in_memory)
    return in_memory


@pytest.fixture
def gateway():
    fake = FakeStorageGateway()
    with (
        patch(GATEWAY_PATH, fake),
        patch(
            ORG_CREDENTIALS_PATH,
            return_value=SimpleNamespace(access_key="org-access", secret_key="org-secret"),
        ),
    ):
        yield fake


class TestS3Backend:
    def test_every_upload_under_the_folder_is_aborted_across_pages(self):
        client = FakeS3Client(page_size=2)
        client.pending_uploads = [(f"org_1/sessions/1/part-{index}", f"u{index}") for index in range(5)]

        aborted = make_s3_backend(client).abort_incomplete_uploads("org_1/sessions/1")

        assert aborted == 5
        assert client.pending_uploads == []

    def test_a_folder_sharing_the_name_as_a_prefix_is_left_alone(self):
        client = FakeS3Client()
        client.pending_uploads = [("org_1/sessions/1/a", "u1"), ("org_1/sessions/10/b", "u2")]

        aborted = make_s3_backend(client).abort_incomplete_uploads("org_1/sessions/1/")

        assert aborted == 1
        assert client.pending_uploads == [("org_1/sessions/10/b", "u2")]

    def test_no_upload_aborts_nothing(self):
        assert make_s3_backend(FakeS3Client()).abort_incomplete_uploads("org_1/sessions/1/") == 0


@pytest.mark.django_db
def test_a_test_run_s_uploads_in_its_own_folder_are_aborted_when_it_ends(gateway, backend, acme):
    result = PythonCodeResult.objects.create(execution_id="exec-1", org_id=acme.id)
    session_credential_service.issue_for_test_run(
        result,
        ["test-runs/exec-1/", "reports/"],
        acme.id,
        own_paths=["test-runs/exec-1/"],
        shared_actions=frozenset(StorageAction),
    )
    own = f"org_{acme.id}/test-runs/exec-1/parked.bin"
    shared = f"org_{acme.id}/reports/parked.bin"
    another_run = f"org_{acme.id}/test-runs/exec-2/parked.bin"
    backend.incomplete_uploads = [own, shared, another_run]

    session_credential_service.revoke_for_test_run("exec-1")

    assert backend.incomplete_uploads == [shared, another_run]


@pytest.mark.django_db
def test_a_session_s_uploads_in_its_own_folder_are_aborted_when_it_ends(gateway, backend, acme):
    session = Session.objects.create(
        graph=Graph.objects.create(org=acme, name="flow"), status=Session.SessionStatus.PENDING
    )
    _issue(session, acme, [None])
    own = f"org_{acme.id}/sessions/{session.pk}/parked.bin"
    shared = f"org_{acme.id}/reports/parked.bin"
    backend.incomplete_uploads = [own, shared]

    session_credential_service.revoke_for_session(session.pk)

    assert backend.incomplete_uploads == [shared]


@pytest.mark.django_db
def test_uploads_are_kept_while_the_account_could_not_be_revoked(backend, acme):
    """The run could still be writing; the manager's cleanup retries the revocation."""
    failing = FakeStorageGateway(delete_error=RuntimeError("backend down"))
    with (
        patch(GATEWAY_PATH, failing),
        patch(
            ORG_CREDENTIALS_PATH,
            return_value=SimpleNamespace(access_key="org-access", secret_key="org-secret"),
        ),
    ):
        result = PythonCodeResult.objects.create(execution_id="exec-1", org_id=acme.id)
        session_credential_service.issue_for_test_run(
            result,
            ["test-runs/exec-1/"],
            acme.id,
            own_paths=["test-runs/exec-1/"],
            shared_actions=frozenset(StorageAction),
        )
        own = f"org_{acme.id}/test-runs/exec-1/parked.bin"
        backend.incomplete_uploads = [own]

        session_credential_service.revoke_for_test_run("exec-1")

    assert backend.incomplete_uploads == [own]
