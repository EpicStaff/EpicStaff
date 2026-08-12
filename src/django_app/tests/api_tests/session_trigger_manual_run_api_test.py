import pytest
from django.urls import reverse
from rest_framework import status

from tables.models.graph_models import GraphOrganizationUser
from tables.models.rbac_models import OrganizationUser
from tables.models.session_models import Session, SessionTrigger
from tests.fixtures import *  # noqa: F401,F403


@pytest.mark.django_db
def test_manual_run_via_api_creates_manual_trigger_with_triggered_by_user(
    api_client, redis_client_mock, session_data, default_org, regular_user
):
    url = reverse("run-session")
    api_client.force_authenticate(user=regular_user)
    api_client.credentials(HTTP_X_ORGANIZATION_ID=str(default_org.id))

    response = api_client.post(url, session_data, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    session = Session.objects.get(pk=response.data["session_id"])

    membership = OrganizationUser.objects.get(user=regular_user, org=default_org)
    graph_user = GraphOrganizationUser.objects.get(
        graph_id=session_data["graph_id"], organization_user=membership
    )

    assert session.trigger.trigger_type == SessionTrigger.TriggerType.MANUAL
    assert session.trigger.triggered_by_user_id == graph_user.id
    assert session.entrypoint is None
