"""A service account's request rate: `requests_per_minute`, across every endpoint it reaches."""

import pytest
from django.core.cache import cache
from plugins import throttles as plugin_throttles
from plugins.identity.service_account_authentication import PluginServiceAccountAuthentication
from rest_framework.request import Request
from rest_framework.settings import api_settings
from rest_framework.test import APIClient, APIRequestFactory
from rest_framework_simplejwt.tokens import RefreshToken
from tables.throttles import NotifyEmailThrottle

from tests.plugins_tests.conftest import GATEWAY_SECRET, mark_running, service_account_client
from tests.plugins_tests.package_builder import WEATHER_LIMITS
from tests.plugins_tests.view_walker import plugin_reachable_views

pytestmark = [pytest.mark.django_db]

ME_URL = "/api/plugin-runtime/me/"
NOW = 1_800_000_000.0  # A minute boundary: 30_000_000 minutes after the epoch.


@pytest.fixture
def frozen_clock(monkeypatch):
    clock = {"now": NOW + 10}
    monkeypatch.setattr(plugin_throttles.time, "time", lambda: clock["now"])
    return clock


@pytest.fixture
def slow_weather(weather_backend):
    return weather_backend(limits={**WEATHER_LIMITS, "requests_per_minute": 2})


@pytest.fixture
def slow_client(slow_weather, service_account_key, acme):
    return service_account_client(service_account_key(slow_weather, acme), acme)


def test_going_over_the_rate_is_throttled_until_the_minute_ends(slow_client, frozen_clock):
    assert [slow_client.get(ME_URL).status_code for _ in range(2)] == [200, 200]

    response = slow_client.get(ME_URL)

    assert response.status_code == 429
    assert response.json()["code"] == "throttled"
    assert response["Retry-After"] == "50"


def test_a_new_minute_starts_a_new_count(slow_client, frozen_clock):
    for _ in range(3):
        slow_client.get(ME_URL)

    frozen_clock["now"] = NOW + 60

    assert slow_client.get(ME_URL).status_code == 200


def test_the_rate_counts_every_endpoint(slow_client, frozen_clock):
    slow_client.get(ME_URL)
    slow_client.get("/api/graphs/")

    assert slow_client.get("/api/graphs/").status_code == 429


def test_each_service_account_has_its_own_count(slow_weather, service_account_key, acme, beta, frozen_clock):
    acme_client = service_account_client(service_account_key(slow_weather, acme), acme)
    beta_client = service_account_client(service_account_key(slow_weather, beta), beta)
    for _ in range(3):
        acme_client.get(ME_URL)

    assert beta_client.get(ME_URL).status_code == 200


def test_the_rate_is_the_effective_limit_after_an_override(slow_weather, service_account_key, acme, frozen_clock):
    type(slow_weather).objects.filter(pk=slow_weather.pk).update(limit_overrides={"requests_per_minute": 1})
    client = service_account_client(service_account_key(slow_weather, acme), acme)

    assert [client.get(ME_URL).status_code for _ in range(2)] == [200, 429]


def test_people_and_api_keys_are_never_counted(admin_acme, acme, issue_api_key, slow_weather):
    person = APIClient()
    person.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(admin_acme).access_token}", HTTP_X_ORGANIZATION_ID=str(acme.pk)
    )
    raw_key, _ = issue_api_key(user=admin_acme)
    api_key = APIClient()
    api_key.credentials(HTTP_X_API_KEY=raw_key, HTTP_X_ORGANIZATION_ID=str(acme.pk))

    for _ in range(5):
        assert person.get("/api/graphs/").status_code == 200
        assert api_key.get("/api/graphs/").status_code == 200

    assert cache.keys("plugins:sa_rate:*") == []


def test_the_throttle_is_a_default_throttle_class():
    assert plugin_throttles.PluginServiceAccountRateThrottle in api_settings.DEFAULT_THROTTLE_CLASSES


def test_every_reachable_view_with_its_own_throttles_keeps_the_defaults(plugins_enabled):
    defaults = set(api_settings.DEFAULT_THROTTLE_CLASSES)

    dropping = sorted(
        {
            f"{view.dotted_path} ({view.route})"
            for view in plugin_reachable_views()
            if view.explicit_throttle_classes and not defaults <= set(view.throttle_classes)
        }
    )

    assert dropping == [], "these views drop the default throttles; extend them instead:\n" + "\n".join(dropping)


def test_notify_email_keys_a_service_account_on_its_rate_bucket(weather_backend, service_account_key, acme):
    plugin = mark_running(weather_backend())
    request = Request(
        APIRequestFactory().post(
            "/api/notify/email/",
            HTTP_AUTHORIZATION=f"PluginKey {service_account_key(plugin, acme)}",
            HTTP_X_PLUGIN_NETWORK_SECRET=GATEWAY_SECRET,
        ),
        authenticators=[PluginServiceAccountAuthentication()],
    )

    key = NotifyEmailThrottle().get_cache_key(request, view=None)

    assert request.user.rate_limit_key in key
