from datetime import UTC, datetime, time, timedelta

import pytest
from django.db import IntegrityError
from django.test import override_settings
from rbac.models import Organization, OrganizationConfig
from tables.services.dashboard.schedule import is_build_due, refresh_minutes

NOW = datetime(2026, 11, 23, 6, 10, tzinfo=UTC)

pytestmark = pytest.mark.usefixtures("refresh_limits")


@pytest.fixture
def refresh_limits():
    with override_settings(
        DASHBOARD_REFRESH_MINUTES=60,
        DASHBOARD_REFRESH_MINUTES_MIN=15,
        DASHBOARD_REFRESH_MINUTES_MAX=1440,
    ):
        yield


@pytest.mark.parametrize(
    ("chosen", "expected"),
    [(None, 60), (5, 15), (2000, 1440), (30, 30)],
)
def test_refresh_minutes_uses_default_and_limits(chosen, expected):
    assert refresh_minutes(chosen) == expected


def test_due_when_never_built():
    assert is_build_due(None, NOW, None, None)


@pytest.mark.parametrize(("minutes_ago", "expected"), [(61, True), (59, False)])
def test_due_after_default_interval(minutes_ago, expected):
    built_at = NOW - timedelta(minutes=minutes_ago)
    assert is_build_due(built_at, NOW, None, None) is expected


def test_chosen_interval_below_min_waits_for_min():
    built_at = NOW - timedelta(minutes=10)
    assert not is_build_due(built_at, NOW, 5, None)


@pytest.mark.parametrize(
    ("built_at", "now", "expected"),
    [
        (datetime(2026, 11, 22, 6, 5, tzinfo=UTC), NOW, True),
        (datetime(2026, 11, 23, 6, 2, tzinfo=UTC), NOW, False),
        (datetime(2026, 11, 22, 6, 5, tzinfo=UTC), datetime(2026, 11, 23, 5, 50, tzinfo=UTC), False),
    ],
)
def test_daily_due_once_time_has_passed_today(built_at, now, expected):
    assert is_build_due(built_at, now, None, time(6, 0)) is expected


@pytest.mark.django_db
def test_config_cannot_have_interval_and_daily_time():
    org = Organization.objects.create(name="Acme")
    config, _ = OrganizationConfig.objects.get_or_create(org=org)
    config.dashboard_refresh_minutes = 30
    config.dashboard_refresh_daily_at = time(6, 0)
    with pytest.raises(IntegrityError):
        config.save()
