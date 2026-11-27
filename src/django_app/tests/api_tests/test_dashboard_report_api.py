from datetime import UTC, datetime, time, timedelta

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils.dateparse import parse_datetime
from rbac.models import OrganizationConfig
from rest_framework import status
from tables.models import DashboardReport, Graph
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


@override_settings(
    DASHBOARD_REFRESH_MINUTES=60, DASHBOARD_REFRESH_MINUTES_MIN=15, DASHBOARD_REFRESH_MINUTES_MAX=1440
)
def test_org_admin_gets_only_own_org_report(client_as, admin_acme, acme, beta):
    Graph.objects.create(name="Acme flow", org=acme)
    Graph.objects.create(name="Beta flow 1", org=beta)
    Graph.objects.create(name="Beta flow 2", org=beta)
    build_report(acme.id)
    build_report(beta.id)

    response = _get(client_as(admin_acme), acme)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["totals"]["flows"] == 1
    report = DashboardReport.objects.get(org=acme)
    assert parse_datetime(response.data["next_build_at"]) == report.built_at + timedelta(minutes=60)
    assert {row["rag_type"] for row in response.data["knowledge_usage"]} == {"naive", "graph"}


def test_next_build_follows_daily_time_of_org(client_as, admin_acme, acme):
    OrganizationConfig.objects.update_or_create(
        org=acme, defaults={"dashboard_refresh_daily_at": time(6, 0)}
    )
    build_report(acme.id)
    DashboardReport.objects.filter(org=acme).update(
        built_at=datetime(2026, 11, 23, 6, 10, tzinfo=UTC)
    )

    response = _get(client_as(admin_acme), acme)

    assert parse_datetime(response.data["next_build_at"]) == datetime(2026, 11, 24, 6, 0, tzinfo=UTC)


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
