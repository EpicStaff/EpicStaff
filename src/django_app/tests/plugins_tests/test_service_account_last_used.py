"""When a plugin's service account last called EpicStaff: one column on the account, whatever its keys."""

from datetime import datetime, timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from plugins.models import PluginGrant, PluginServiceAccount

from tests.plugins_tests.conftest import service_account_client

pytestmark = [pytest.mark.django_db]

ME_URL = "/api/plugin-runtime/me/"
GRANTS_URL = "/api/admin/plugins/weather/grants/"
ORGANIZATION_ACCOUNTS_URL = "/api/plugins/service-accounts/"


@pytest.fixture
def weather(weather_backend):
    return weather_backend()


@pytest.fixture
def acme_key(weather, service_account_key, acme):
    return service_account_key(weather, acme)


def _last_used(acme):
    return PluginServiceAccount.objects.get(grant__org=acme).last_used_at


def test_a_call_records_the_use_on_the_account(acme_key, acme):
    before = timezone.now()

    assert service_account_client(acme_key, acme).get(ME_URL).status_code == 200

    assert _last_used(acme) >= before


def test_the_use_is_written_at_most_once_a_minute(acme_key, acme, monkeypatch):
    client = service_account_client(acme_key, acme)
    client.get(ME_URL)
    first_use = _last_used(acme)

    with CaptureQueriesContext(connection) as captured:
        client.get(ME_URL)
    assert _last_used(acme) == first_use
    assert not [query for query in captured.captured_queries if query["sql"].startswith('UPDATE "plugins_pluginserviceaccount"')]

    monkeypatch.setattr(timezone, "now", lambda: first_use + timedelta(seconds=61))
    client.get(ME_URL)
    assert _last_used(acme) == first_use + timedelta(seconds=61)


def test_a_new_key_carries_the_use_of_the_previous_one(weather, service_account_key, acme_key, acme, monkeypatch):
    service_account_client(acme_key, acme).get(ME_URL)
    first_use = _last_used(acme)
    second_key = service_account_key(weather, acme)

    # Within the minute: the account was just used, by whichever key.
    service_account_client(second_key, acme).get(ME_URL)

    assert _last_used(acme) == first_use


def test_both_lists_read_the_account_s_last_use(acme_key, acme, superadmin_client, client_as, admin_acme):
    service_account_client(acme_key, acme).get(ME_URL)
    used_at = _last_used(acme)
    organization_client = client_as(admin_acme)
    organization_client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.pk))

    granted = superadmin_client.get(GRANTS_URL).json()
    listed = organization_client.get(ORGANIZATION_ACCOUNTS_URL).json()

    grant_row = next(row for row in _rows(granted) if row["organization"]["id"] == acme.pk)
    assert datetime.fromisoformat(grant_row["service_account"]["key_last_used_at"]) == used_at
    assert [datetime.fromisoformat(row["key_last_used_at"]) for row in listed] == [used_at]


def test_an_account_never_used_shows_no_last_use(weather, superadmin, acme, superadmin_client):
    from plugins.lifecycle.grant_service import PluginGrantService

    PluginGrantService().grant(weather.identifier, acme.pk, superadmin)

    rows = _rows(superadmin_client.get(GRANTS_URL).json())

    assert [row["service_account"]["key_last_used_at"] for row in rows] == [None]
    assert PluginGrant.objects.get(org=acme).service_account.last_used_at is None


def _rows(body):
    return body["results"] if isinstance(body, dict) and "results" in body else body
