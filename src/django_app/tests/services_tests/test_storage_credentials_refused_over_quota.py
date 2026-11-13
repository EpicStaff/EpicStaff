"""No temporary storage credentials are minted for an organization over its storage quota.

Run code holding temporary credentials writes straight to the object store, past the upload
quota check, so the mint is the only place that can stop an organization over its quota from
writing more. Over the quota, every entry point (flow session, test run, realtime chat) is
refused with 409 `organization_storage_full` before the storage backend is contacted, and no
account row is left. At the quota, minting goes on as before. Only the minting organization's
own bytes count: another organization's usage never refuses it.

The storage backend's admin API is the external boundary, replaced by FakeStorageGateway.
"""

import uuid

import pytest
from django.utils import timezone

from storage_credentials.models import TemporaryStorageAccount
from storage_credentials.services.session_credential_service import session_credential_service
from storage_credentials.tests.session_data_builders import (
    make_graph,
    make_session_data,
    make_storage_python_node,
)
from tables.models import (
    Graph,
    OrganizationStorageUsage,
    PythonCodeResult,
    RealtimeAgentChat,
    Session,
    StorageFile,
)
from tables.services.run_admission import RunAdmissionRefusedError
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db

QUOTA = 1000


@pytest.fixture(autouse=True)
def small_quota(settings):
    settings.ORG_STORAGE_QUOTA = QUOTA


def _store_bytes(org, size: int, path: str = "stored.bin") -> None:
    StorageFile.objects.create(org=org, path=path, name=path, item_type="file", size=size)


def _issue_for_test_run(org):
    result = PythonCodeResult.objects.create(execution_id=f"exec-{org.pk}", org=org)
    return session_credential_service.issue_for_test_run(
        python_code_result=result, storage_allowed_paths=["test-runs/x/"], org_id=org.pk
    )


def _issue_for_session(org):
    graph = Graph.objects.create(org=org, name="quota-flow")
    session = Session.objects.create(graph=graph, status=Session.SessionStatus.PENDING)
    session_data = make_session_data(
        session.pk, make_graph([make_storage_python_node(org_id=org.pk)])
    )
    return session_credential_service.issue_for_session(
        session_data=session_data, session_orm=session, org=org
    )


def _issue_for_realtime_chat(org):
    chat = RealtimeAgentChat.objects.create(connection_key=f"quota-chat-{org.pk}")
    return session_credential_service.issue_for_realtime_chat(
        realtime_agent_chat=chat, storage_allowed_paths=["shared/"], org_id=org.pk
    )


ENTRY_POINTS = [_issue_for_test_run, _issue_for_session, _issue_for_realtime_chat]
ENTRY_POINT_IDS = ["test-run", "session", "realtime-chat"]


@pytest.mark.parametrize("issue", ENTRY_POINTS, ids=ENTRY_POINT_IDS)
def test_an_organization_over_its_quota_gets_no_credentials(gateway, acme, issue):
    _store_bytes(acme, QUOTA + 1)

    with pytest.raises(RunAdmissionRefusedError) as refusal:
        issue(acme)

    assert (refusal.value.status_code, refusal.value.default_code) == (
        409,
        "organization_storage_full",
    )
    assert gateway.created == []
    assert not TemporaryStorageAccount.objects.exists()
    assert not OrganizationStorageUsage.objects.filter(org=acme).exists()


@pytest.mark.parametrize("issue", ENTRY_POINTS, ids=ENTRY_POINT_IDS)
def test_an_organization_exactly_at_its_quota_still_gets_credentials(gateway, acme, issue):
    _store_bytes(acme, QUOTA)

    credentials = issue(acme)

    assert credentials.access_key == "temp-access-1"
    assert list(TemporaryStorageAccount.objects.values_list("access_key", flat=True)) == [
        "temp-access-1"
    ]


def test_another_organization_over_its_quota_never_refuses_this_one(gateway, acme, beta):
    _store_bytes(beta, QUOTA * 50)
    _store_bytes(acme, QUOTA)

    credentials = _issue_for_test_run(acme)

    assert credentials.access_key == "temp-access-1"
    with pytest.raises(RunAdmissionRefusedError):
        _issue_for_test_run(beta)
    assert len(gateway.created) == 1


def test_files_in_the_recycle_bin_count_toward_the_refusal(gateway, acme):
    _store_bytes(acme, QUOTA)
    StorageFile.all_objects.create(
        org=acme,
        path="binned.bin",
        name="binned.bin",
        item_type="file",
        size=1,
        active=False,
        soft_deleted_at=timezone.now(),
        soft_delete_batch=uuid.uuid4(),
    )

    with pytest.raises(RunAdmissionRefusedError):
        _issue_for_test_run(acme)
    assert gateway.created == []
