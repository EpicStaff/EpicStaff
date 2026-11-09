"""A flow run that needs storage is stopped before crew hears of it while its organization is
over its storage quota.

The refusal comes from minting the session's storage credentials, after the session row
exists, so the session is stopped with the refusal as its reason, nothing is published and
nothing is minted; POST /api/run-session/ answers 409 `organization_storage_full`. At the
quota the same flow gets its credentials and is published.

The session payload is built by a stub carrying one storage-demanding python node; the
credential service, run_session and the view are real. Redis publish and the storage
backend's admin API (FakeStorageGateway) are the external boundaries.
"""

import pytest

from storage_credentials.models import TemporaryStorageAccount
from storage_credentials.tests.session_data_builders import (
    make_graph,
    make_session_data,
    make_storage_python_node,
)
from tables.models import Graph, Session, StartNode, StorageFile
from tables.services.run_admission import RunAdmissionRefusedError
from tables.services.session_manager_service import SessionManagerService
from tables.services.trigger_spec import TriggerSpec

pytestmark = pytest.mark.django_db

QUOTA = 1000


@pytest.fixture(autouse=True)
def small_quota(settings):
    settings.ORG_STORAGE_QUOTA = QUOTA


@pytest.fixture
def flow(default_org):
    graph = Graph.objects.create(name="storage-full-flow", org=default_org)
    StartNode.objects.create(graph=graph, variables={"variables": {}})
    return graph


@pytest.fixture
def published(monkeypatch, default_org):
    """Build a payload with a storage-demanding node and record what reaches crew."""
    session_manager = SessionManagerService()
    sent = []
    monkeypatch.setattr(
        session_manager,
        "create_session_data",
        lambda session, **kwargs: make_session_data(
            session.pk, make_graph([make_storage_python_node(org_id=default_org.pk)])
        ),
    )
    monkeypatch.setattr(
        session_manager.redis_service,
        "publish_session_data",
        lambda **kwargs: sent.append(kwargs) or 2,
    )
    yield sent


def _fill_storage(org, size: int) -> None:
    StorageFile.objects.create(org=org, path="full.bin", name="full.bin", item_type="file", size=size)


def test_a_flow_over_quota_is_stopped_and_never_published(
    gateway, published, flow, default_org, regular_user
):
    _fill_storage(default_org, QUOTA + 1)

    with pytest.raises(RunAdmissionRefusedError) as refusal:
        SessionManagerService().run_session(
            graph_id=flow.pk, variables={}, user=regular_user, trigger=TriggerSpec.manual()
        )

    assert refusal.value.default_code == "organization_storage_full"
    session = Session.objects.get(graph=flow)
    assert session.status == Session.SessionStatus.STOP
    assert session.status_data == {"reason": str(refusal.value.detail)}
    assert session.finished_at is not None
    assert published == []
    assert gateway.created == []
    assert not TemporaryStorageAccount.objects.exists()


def test_run_session_endpoint_answers_storage_full_with_409(
    gateway, published, flow, default_org, auth_client
):
    _fill_storage(default_org, QUOTA + 1)

    response = auth_client.post("/api/run-session/", {"graph_id": flow.pk}, format="json")

    assert response.status_code == 409, response.content
    body = response.json()
    assert (body["status_code"], body["code"]) == (409, "organization_storage_full")
    assert list(Session.objects.filter(graph=flow).values_list("status", flat=True)) == [
        Session.SessionStatus.STOP
    ]
    assert published == []


def test_a_flow_at_the_quota_is_published_with_its_credentials(
    gateway, published, flow, default_org, regular_user
):
    _fill_storage(default_org, QUOTA)

    SessionManagerService().run_session(
        graph_id=flow.pk, variables={}, user=regular_user, trigger=TriggerSpec.manual()
    )

    (sent,) = published
    assert sent["storage_credentials"].access_key == "temp-access-1"
