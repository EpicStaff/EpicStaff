from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework import status
from tables.models import DURATION_BUCKET_COUNT, DashboardSessionDailyStat
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db

URL = reverse("dashboard-stats")


def _get(client, org, **params):
    return client.get(URL, params, HTTP_X_ORGANIZATION_ID=str(org.id))


def _stat(org, day, status, sessions, source_ref="1", **tokens):
    DashboardSessionDailyStat.objects.create(
        org=org,
        day=day,
        graph_id=1,
        graph_name="Orders",
        status=status,
        trigger_type="manual",
        source_kind="user",
        source_ref=source_ref,
        session_count=sessions,
        duration_histogram=[0] * DURATION_BUCKET_COUNT,
        **tokens,
    )


def test_months_are_summed_and_empty_months_are_zero(client_as, admin_acme, acme):
    _stat(acme, date(2026, 10, 5), "end", 3, total_tokens=100, cost_usd=Decimal("0.5"))
    _stat(acme, date(2026, 10, 9), "end", 2, total_tokens=50, cost_usd=Decimal("0.25"))
    _stat(acme, date(2026, 11, 20), "error", 1)

    response = _get(client_as(admin_acme), acme, **{"from": "2026-09-15", "to": "2026-11-23"}, group="month")

    assert response.status_code == status.HTTP_200_OK
    periods = response.data["periods"]
    assert [p["period"] for p in periods] == ["2026-09-01", "2026-10-01", "2026-11-01"]
    assert periods[0]["by_status"] == {"end": 0, "error": 0, "stop": 0, "expired": 0}
    assert periods[1]["by_status"]["end"] == 5
    assert periods[1]["tokens"]["total"] == 150
    assert Decimal(periods[1]["tokens"]["cost_usd"]) == Decimal("0.75")
    assert periods[2]["by_status"]["error"] == 1


def test_days_sum_rows_of_own_org_only(client_as, admin_acme, acme, beta):
    _stat(acme, date(2026, 11, 22), "end", 2, source_ref="1")
    _stat(acme, date(2026, 11, 22), "end", 3, source_ref="2")
    _stat(beta, date(2026, 11, 22), "end", 7)

    response = _get(client_as(admin_acme), acme, **{"from": "2026-11-22", "to": "2026-11-23"}, group="day")

    assert [p["by_status"]["end"] for p in response.data["periods"]] == [5, 0]


@pytest.mark.parametrize(
    "params",
    [
        {"from": "2026-11-23", "to": "2026-11-01", "group": "day"},
        {"from": "2026-11-01", "to": "2026-11-23", "group": "week"},
    ],
)
def test_invalid_query_is_400(client_as, admin_acme, acme, params):
    assert _get(client_as(admin_acme), acme, **params).status_code == status.HTTP_400_BAD_REQUEST


def test_member_without_dashboard_read_is_refused(client_as, member_only, acme):
    response = _get(client_as(member_only), acme, **{"from": "2026-11-01", "to": "2026-11-23"}, group="day")

    assert response.status_code == status.HTTP_403_FORBIDDEN
