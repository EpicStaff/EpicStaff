"""A flow's sessions follow it into the recycle bin.

Binning a flow keeps its sessions linked to it and hides them from every session
endpoint (the same 404 as a missing session); restoring the flow brings them back,
purging it deletes them.
"""

import uuid

import pytest
from django.utils import timezone

from rbac.models.enums import Permission, ResourceType
from tables.models import Graph
from tables.models.graph_models import GraphSessionMessage, ScheduleTriggerNode
from tables.models.session_models import Session, SessionTrigger
from tests.api_tests.recycle_bin_cases import FLOWS_URL
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

SESSIONS_URL = "/api/sessions/"


@pytest.fixture
def flow(acme):
    return Graph.objects.create(name="Followed flow", org=acme)


@pytest.fixture
def session(flow):
    session = Session.objects.create(graph=flow, status=Session.SessionStatus.END, variables={})
    GraphSessionMessage.objects.create(
        session=session,
        created_at=timezone.now(),
        message_data={"message_type": "start"},
        uuid=uuid.uuid4(),
    )
    return session


@pytest.fixture
def binned_flow(acme_admin_client, flow, session):
    assert acme_admin_client.delete(f"{FLOWS_URL}{flow.pk}/").status_code == 204
    return flow


@pytest.fixture
def beta_flows_client(client_as, custom_role_user, beta):
    """A member of Beta allowed everything on flows, with Beta as the active org."""
    every_flow_permission = Permission(sum(Permission))
    user = custom_role_user(beta, "beta-flows@example.com", {ResourceType.FLOWS: every_flow_permission})
    client = client_as(user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(beta.id))
    return client


SESSION_ENDPOINTS = [
    ("get", "{id}/"),
    ("delete", "{id}/"),
    ("get", "{id}/export/"),
    ("get", "{id}/warnings/"),
    ("get", "{id}/output-files/"),
    ("get", "{id}/get-updates/"),
    ("post", "{id}/stop/"),
]


def _listed_ids(response):
    return {row["id"] for row in response.data["results"]}


@pytest.mark.django_db
class TestBinningTheFlow:
    def test_keeps_the_session_its_link_and_its_messages(self, binned_flow, session):
        session.refresh_from_db()
        assert session.graph_id == binned_flow.pk
        assert GraphSessionMessage.objects.filter(session=session).count() == 1

    @pytest.mark.parametrize("method, path", SESSION_ENDPOINTS)
    def test_hides_the_session_from_its_endpoints(
        self, acme_admin_client, binned_flow, session, method, path
    ):
        response = getattr(acme_admin_client, method)(SESSIONS_URL + path.format(id=session.pk))

        assert response.status_code == 404
        assert Session.objects.filter(pk=session.pk).exists()

    @pytest.mark.parametrize("method, path", SESSION_ENDPOINTS)
    def test_the_same_endpoints_answer_for_a_session_of_a_live_flow(
        self, acme_admin_client, session, method, path
    ):
        response = getattr(acme_admin_client, method)(SESSIONS_URL + path.format(id=session.pk))

        assert response.status_code != 404, response.content

    def test_leaves_the_session_out_of_the_list_and_the_status_counts(
        self, acme_admin_client, binned_flow, session, acme
    ):
        live_flow = Graph.objects.create(name="Live flow", org=acme)
        live_session = Session.objects.create(graph=live_flow, status=Session.SessionStatus.END)

        listed = acme_admin_client.get(SESSIONS_URL)
        statuses = acme_admin_client.get(f"{SESSIONS_URL}statuses/")

        assert _listed_ids(listed) == {live_session.pk}
        assert set(statuses.data) == {live_flow.pk}

    def test_leaves_the_session_messages_out(self, acme_admin_client, binned_flow, session):
        response = acme_admin_client.get(f"/api/graph-session-messages/?session_id={session.pk}")

        assert response.status_code == 200
        assert response.data["results"] == []

    def test_refuses_to_export_the_session(self, acme_admin_client, binned_flow, session):
        bulk = acme_admin_client.post(
            f"{SESSIONS_URL}bulk-export/", {"ids": [session.pk]}, format="json"
        )
        everything = acme_admin_client.post(f"{SESSIONS_URL}export_all/", {}, format="json")

        assert bulk.status_code == 400
        assert everything.status_code == 404

    def test_bulk_delete_leaves_the_session_alone(self, acme_admin_client, binned_flow, session):
        response = acme_admin_client.post(
            f"{SESSIONS_URL}bulk_delete/", {"ids": [session.pk]}, format="json"
        )

        assert response.status_code == 200
        assert response.data["deleted"] == 0
        assert Session.objects.filter(pk=session.pk).exists()


@pytest.mark.django_db
class TestRestoringTheFlow:
    def test_brings_the_session_back(self, acme_admin_client, binned_flow, session):
        assert acme_admin_client.post(f"{FLOWS_URL}{binned_flow.pk}/restore/").status_code == 200

        detail = acme_admin_client.get(f"{SESSIONS_URL}{session.pk}/")
        listed = acme_admin_client.get(SESSIONS_URL)
        messages = acme_admin_client.get(f"/api/graph-session-messages/?session_id={session.pk}")

        assert detail.status_code == 200
        assert detail.data["graph"] == binned_flow.pk
        assert _listed_ids(listed) == {session.pk}
        assert len(messages.data["results"]) == 1

    def test_session_still_names_the_trigger_node_that_started_it(
        self, acme_admin_client, flow, session
    ):
        node = ScheduleTriggerNode.objects.create(graph=flow, node_name="nightly", is_active=True)
        SessionTrigger.objects.create(
            session=session,
            trigger_type=SessionTrigger.TriggerType.SCHEDULE,
            schedule_trigger_node=node,
            node_name="nightly",
        )
        assert acme_admin_client.delete(f"{FLOWS_URL}{flow.pk}/").status_code == 204
        assert acme_admin_client.post(f"{FLOWS_URL}{flow.pk}/restore/").status_code == 200

        detail = acme_admin_client.get(f"{SESSIONS_URL}{session.pk}/")

        assert detail.status_code == 200
        assert detail.data["trigger"]["trigger_type"] == SessionTrigger.TriggerType.SCHEDULE
        assert detail.data["trigger"]["trigger_id"] == node.pk

    def test_still_hides_the_session_from_another_org(
        self, acme_admin_client, beta_flows_client, binned_flow, session
    ):
        restored = acme_admin_client.post(f"{FLOWS_URL}{binned_flow.pk}/restore/")
        assert restored.status_code == 200

        assert beta_flows_client.get(f"{SESSIONS_URL}{session.pk}/").status_code == 404
        assert beta_flows_client.get(f"{SESSIONS_URL}{session.pk}/get-updates/").status_code == 404
        assert _listed_ids(beta_flows_client.get(SESSIONS_URL)) == set()


@pytest.mark.django_db
class TestPurgingTheFlow:
    def test_deletes_its_sessions_with_their_sub_sessions_and_messages(
        self, superadmin_in_acme, binned_flow, session, acme
    ):
        subflow = Graph.objects.create(name="Subflow", org=acme)
        sub_session = Session.objects.create(
            graph=subflow, parent_session=session, status=Session.SessionStatus.END
        )

        response = superadmin_in_acme.delete(f"{FLOWS_URL}{binned_flow.pk}/purge/")

        assert response.status_code == 204
        assert not Session.objects.filter(pk__in=[session.pk, sub_session.pk]).exists()
        assert not GraphSessionMessage.objects.filter(session_id=session.pk).exists()
        assert Graph.objects.filter(pk=subflow.pk).exists()
