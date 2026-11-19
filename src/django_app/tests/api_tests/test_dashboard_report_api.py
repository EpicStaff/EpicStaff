import pytest
from django.urls import reverse
from rest_framework import status
from tables.models import Graph
from tables.services.dashboard.report import build_report
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db

URL = reverse("dashboard-report")


def _get(client, org):
    return client.get(URL, HTTP_X_ORGANIZATION_ID=str(org.id))


def test_member_without_dashboard_read_is_refused(client_as, member_only, acme):
    build_report(acme.id)

    response = _get(client_as(member_only), acme)

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_org_admin_gets_only_own_org_report(client_as, admin_acme, acme, beta):
    Graph.objects.create(name="Acme flow", org=acme)
    Graph.objects.create(name="Beta flow 1", org=beta)
    Graph.objects.create(name="Beta flow 2", org=beta)
    build_report(acme.id)
    build_report(beta.id)

    response = _get(client_as(admin_acme), acme)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["totals"]["flows"] == 1
    assert response.data["next_build_at"] is None
    assert {row["rag_type"] for row in response.data["knowledge_usage"]} == {"naive", "graph"}


def test_report_not_ready_before_first_build(client_as, admin_acme, acme):
    response = _get(client_as(admin_acme), acme)

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.data == {"code": "report_not_ready"}


def test_api_key_of_org_admin_gets_report(api_client, issue_api_key, admin_acme, acme):
    build_report(acme.id)
    raw_key, _ = issue_api_key(user=admin_acme, org=acme)
    api_client.credentials(HTTP_X_API_KEY=raw_key)

    response = _get(api_client, acme)

    assert response.status_code == status.HTTP_200_OK
