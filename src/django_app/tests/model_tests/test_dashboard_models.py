from datetime import date

import pytest
from django.db import IntegrityError
from rbac.models import Organization
from tables.models import (
    DURATION_BUCKET_COUNT,
    DURATION_BUCKET_UPPER_SECONDS,
    DashboardSessionDailyStat,
    Graph,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Acme")


def _stat(org, graph_id, **fields):
    return DashboardSessionDailyStat.objects.create(
        org=org,
        day=date(2026, 11, 19),
        graph_id=graph_id,
        graph_name="Orders",
        status="end",
        trigger_type="manual",
        source_kind="user",
        source_ref="7",
        duration_histogram=[0] * DURATION_BUCKET_COUNT,
        **fields,
    )


def test_histogram_has_fifteen_buckets():
    assert DURATION_BUCKET_COUNT == len(DURATION_BUCKET_UPPER_SECONDS) + 1 == 15


def test_daily_stat_is_unique_per_set_of_dimensions(org):
    _stat(org, graph_id=1)
    _stat(org, graph_id=1, is_test=True)

    with pytest.raises(IntegrityError):
        _stat(org, graph_id=1)


def test_deleting_flow_keeps_daily_stat(org):
    flow = Graph.objects.create(name="Orders", org=org)
    stat = _stat(org, graph_id=flow.id)

    Graph.all_objects.filter(pk=flow.pk).delete()

    assert DashboardSessionDailyStat.objects.filter(pk=stat.pk).exists()
