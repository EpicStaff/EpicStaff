"""Service-account keys: their form, where they authenticate, and how minting rotates them."""

import hashlib
import re
from datetime import timedelta

import pytest
from django.db import IntegrityError, connection, transaction
from django.utils import timezone
from plugins.identity.service_account_keys import ServiceAccountKeyService
from plugins.lifecycle.grant_service import PluginGrantService
from plugins.lifecycle.suspension_service import PluginSuspensionService
from plugins.models import (
    GrantState,
    PluginGrant,
    PluginServiceAccount,
    PluginServiceAccountKey,
    ServiceAccountKeyPurpose,
)
from rbac.models import Organization
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from tests.plugins_tests.conftest import GATEWAY_SECRET, NODE_KEY, service_account_client

pytestmark = [pytest.mark.django_db]

ME_URL = "/api/plugin-runtime/me/"
KEY_PATTERN = re.compile(r"^esp-[A-Za-z0-9_-]{43}$")


@pytest.fixture
def weather(weather_backend):
    return weather_backend()


@pytest.fixture
def acme_key(weather, service_account_key, acme):
    return service_account_key(weather, acme)


def _refused(response):
    assert response.status_code == 401
    assert response.json()["code"] == "service_account_not_authenticated"


# ---- form and storage ----


def test_a_key_has_the_documented_form_and_only_its_hash_is_stored(acme_key):
    stored = PluginServiceAccountKey.objects.get()

    assert KEY_PATTERN.match(acme_key)
    assert len(acme_key) == 47
    assert stored.prefix == acme_key[:12]
    assert stored.key_hash == hashlib.sha256(acme_key.encode()).hexdigest()
    assert acme_key not in {value for value in vars(stored).values() if isinstance(value, str)}


def test_the_runtime_api_challenges_with_the_plugin_key_scheme(weather, acme):
    response = service_account_client("esp-" + "z" * 43, acme).get(ME_URL)

    _refused(response)
    assert response["WWW-Authenticate"] == "PluginKey"


def test_a_valid_key_authenticates_through_the_internal_listener(acme_key, acme):
    response = service_account_client(acme_key, acme).get(ME_URL)

    assert response.status_code == 200
    assert response.json()["organization"]["id"] == acme.pk


# ---- each check, in order ----


@pytest.mark.parametrize("network_secret", [None, "", "wrong", GATEWAY_SECRET[:-1]], ids=["missing", "empty", "wrong", "prefix"])
def test_a_key_from_outside_the_internal_listener_is_refused(acme_key, acme, network_secret):
    _refused(service_account_client(acme_key, acme, network_secret=network_secret).get(ME_URL))


def test_no_key_authenticates_while_the_gateway_secret_is_unconfigured(acme_key, acme, settings):
    settings.PLUGINS_GATEWAY_SECRET = "none"

    _refused(service_account_client(acme_key, acme, network_secret="none").get(ME_URL))


@pytest.mark.parametrize("raw_key", ["esp-" + "x" * 43, "", "   "], ids=["unknown", "empty", "blank"])
def test_an_unknown_key_is_refused(weather, acme, raw_key):
    _refused(service_account_client(raw_key, acme).get(ME_URL))


def test_a_revoked_key_is_refused(acme_key, acme):
    PluginServiceAccountKey.objects.update(revoked_at=timezone.now())

    _refused(service_account_client(acme_key, acme).get(ME_URL))


def test_a_revoked_service_account_is_refused(acme_key, acme):
    PluginServiceAccount.objects.update(revoked_at=timezone.now())

    _refused(service_account_client(acme_key, acme).get(ME_URL))


@pytest.mark.parametrize("state", [GrantState.INSTALL_FAILED, GrantState.SUSPENDED, GrantState.PURGING])
def test_a_grant_that_holds_no_key_is_refused(acme_key, acme, state):
    PluginGrant.objects.update(state=state)

    _refused(service_account_client(acme_key, acme).get(ME_URL))


def test_a_granting_grant_holds_a_key(acme_key, acme):
    PluginGrant.objects.update(state=GrantState.GRANTING)

    response = service_account_client(acme_key, acme).get(ME_URL)

    assert response.status_code == 200
    assert response.json()["grant_state"] == "granting"


def test_a_key_of_an_inactive_organization_is_refused(acme_key, acme):
    Organization.objects.filter(pk=acme.pk).update(is_active=False)

    _refused(service_account_client(acme_key, acme).get(ME_URL))


def test_the_plugin_state_is_not_consulted(acme_key, acme, weather):
    type(weather).objects.filter(pk=weather.pk).update(state="failed")

    assert service_account_client(acme_key, acme).get(ME_URL).status_code == 200


def test_a_refusal_never_falls_through_to_anonymous(acme, weather):
    response = service_account_client("esp-" + "y" * 43, acme).get("/api/graphs/")

    _refused(response)


def test_a_person_s_token_does_not_open_the_plugin_runtime_api(acme_key, admin_acme, acme):
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(admin_acme).access_token}",
        HTTP_X_ORGANIZATION_ID=str(acme.pk),
        HTTP_X_PLUGIN_NETWORK_SECRET=GATEWAY_SECRET,
    )

    assert client.get(ME_URL).status_code == 401


# ---- minting ----


def test_minting_keeps_the_previous_key_for_ten_minutes_then_refuses_it(weather, service_account_key, acme, monkeypatch):
    first = service_account_key(weather, acme)
    minted_at = timezone.now()
    second = service_account_key(weather, acme)
    previous = PluginServiceAccountKey.objects.get(prefix=first[:12])

    assert abs(previous.expires_at - (minted_at + timedelta(minutes=10))) < timedelta(seconds=5)
    assert service_account_client(first, acme).get(ME_URL).status_code == 200
    assert service_account_client(second, acme).get(ME_URL).status_code == 200

    monkeypatch.setattr(timezone, "now", lambda: previous.expires_at + timedelta(seconds=1))

    _refused(service_account_client(first, acme).get(ME_URL))
    assert service_account_client(second, acme).get(ME_URL).status_code == 200


def test_minting_again_revokes_the_key_before_the_previous_one_at_once(weather, service_account_key, acme):
    first = service_account_key(weather, acme)
    second = service_account_key(weather, acme)
    third = service_account_key(weather, acme)

    _refused(service_account_client(first, acme).get(ME_URL))
    assert service_account_client(second, acme).get(ME_URL).status_code == 200
    assert service_account_client(third, acme).get(ME_URL).status_code == 200
    assert PluginServiceAccountKey.objects.filter(revoked_at__isnull=True).count() == 2


def test_at_most_two_keys_of_an_account_are_ever_valid(weather, service_account_key, acme):
    for _ in range(5):
        service_account_key(weather, acme)

    valid = PluginServiceAccountKey.objects.filter(revoked_at__isnull=True)
    assert valid.count() == 2
    assert valid.filter(expires_at__isnull=True).count() == 1


def test_minting_gives_each_key_holding_organization_one_key_in_a_fixed_number_of_queries(
    weather, superadmin, django_assert_num_queries
):
    organizations = [Organization.objects.create(name=f"mint-{index}") for index in range(4)]
    for organization in organizations:
        PluginGrantService().grant(weather.identifier, organization.pk, superadmin)
    PluginGrant.objects.filter(org=organizations[3]).update(state=GrantState.INSTALL_FAILED)
    ServiceAccountKeyService().mint_for_plugin(weather)

    with django_assert_num_queries(4 + 2):  # four, inside a savepoint pair
        minted = ServiceAccountKeyService().mint_for_plugin(weather)

    assert sorted(key.service_account.grant.org_id for key in minted) == sorted(org.pk for org in organizations[:3])


def test_a_mint_that_waited_for_the_lock_still_gives_the_superseded_key_ten_minutes(weather, service_account_key, acme, monkeypatch):
    service_account_key(weather, acme)
    lock_taken_at = timezone.now() + timedelta(minutes=3)

    def wait_for_the_lock(execute, sql, params, many, context):
        result = execute(sql, params, many, context)
        if "FOR UPDATE" in sql:
            # Another mint held the accounts; the clock moved on while this one waited.
            monkeypatch.setattr(timezone, "now", lambda: lock_taken_at)
        return result

    with connection.execute_wrapper(wait_for_the_lock):
        ServiceAccountKeyService().mint_for_plugin(weather)

    superseded = PluginServiceAccountKey.objects.get(expires_at__isnull=False, revoked_at__isnull=True)
    assert superseded.expires_at == lock_taken_at + timedelta(minutes=10)


def test_a_committed_mint_writes_its_log_line(weather, service_account_key, acme, log_messages, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        service_account_key(weather, acme)

    assert [line for line in log_messages if line.startswith("plugins.service_account.keys_minted")] == [
        f"plugins.service_account.keys_minted plugin=weather org_ids={acme.pk} count=1"
    ]


def test_a_rolled_back_mint_writes_no_log_line(weather, service_account_key, acme, log_messages, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        service_account_key(weather, acme)
    log_messages.clear()

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        with pytest.raises(RuntimeError), transaction.atomic():
            ServiceAccountKeyService().mint_for_plugin(weather)
            raise RuntimeError("the caller fails after the mint")

    assert callbacks == []
    assert not [line for line in log_messages if line.startswith("plugins.service_account.keys_minted")]


def test_a_failed_mint_leaves_no_new_key(weather, service_account_key, acme, monkeypatch):
    service_account_key(weather, acme)
    before = set(PluginServiceAccountKey.objects.values_list("pk", "expires_at", "revoked_at"))

    def fail(*args, **kwargs):
        raise RuntimeError("insert failed")

    monkeypatch.setattr(PluginServiceAccountKey.objects, "bulk_create", fail)

    with pytest.raises(RuntimeError):
        ServiceAccountKeyService().mint_for_plugin(weather)

    assert set(PluginServiceAccountKey.objects.values_list("pk", "expires_at", "revoked_at")) == before


# ---- plugins off ----


def test_with_plugins_off_a_plugin_key_is_never_read(acme_key, acme, settings):
    settings.PLUGINS_ENABLED = False

    response = service_account_client(acme_key, acme).get("/api/graphs/")

    assert response.status_code == 401
    assert response.json()["code"] == "not_authenticated"


# ---- node keys ----


@pytest.mark.parametrize("network_secret", [None, "wrong"], ids=["missing", "wrong"])
def test_a_node_key_also_needs_the_internal_listener(plugin_node, network_secret, service_account_platform):
    client = APIClient()
    headers = {"HTTP_AUTHORIZATION": f"PluginNodeKey {NODE_KEY}"}
    if network_secret is not None:
        headers["HTTP_X_PLUGIN_NETWORK_SECRET"] = network_secret
    client.credentials(**headers)

    response = client.get("/api/plugin-nodes/self/desired-state/")

    assert response.status_code == 401
    assert response.json()["code"] == "node_not_authenticated"


def test_a_service_account_key_is_no_node_key(acme_key, acme):
    response = service_account_client(acme_key, acme).get("/api/plugin-nodes/self/desired-state/")

    assert response.status_code == 401
    assert response.json()["code"] == "node_not_authenticated"



# ---- development keys: only through the development API listener, only in development mode ----

DESIRED_STATE_URL = "/api/plugin-nodes/self/desired-state/"


def _development_key(plugin, organization) -> str:
    minted = ServiceAccountKeyService().mint_development_keys(plugin)
    return next(key.raw_key for key in minted if key.service_account.grant.org_id == organization.pk)


def _through_development_listener(raw_key, organization, value="1"):
    return service_account_client(raw_key, organization, development_listener=value)


@pytest.fixture
def development_key(weather, acme_key, acme):
    return _development_key(weather, acme)


def _refusals(log_messages):
    return [line for line in log_messages if line.startswith("plugins.service_account.refused")]


@pytest.mark.usefixtures("development_mode")
def test_a_development_key_authenticates_through_the_development_listener_in_its_organization(development_key, acme):
    response = _through_development_listener(development_key, acme).get(ME_URL)

    assert response.status_code == 200
    assert response.json()["organization"]["id"] == acme.pk


@pytest.mark.usefixtures("development_mode")
def test_a_development_key_through_the_internal_listener_is_refused(development_key, acme, log_messages):
    _refused(service_account_client(development_key, acme).get(ME_URL))

    assert _refusals(log_messages) == ["plugins.service_account.refused plugin=weather reason=wrong_listener"]


@pytest.mark.usefixtures("development_mode")
@pytest.mark.parametrize("value", ["0", "true", ""], ids=["zero", "true", "empty"])
def test_only_the_development_listener_s_own_value_lets_a_development_key_in(development_key, acme, value):
    _refused(_through_development_listener(development_key, acme, value).get(ME_URL))


def test_a_development_key_is_refused_while_the_mode_is_off(development_key, acme, log_messages):
    _refused(_through_development_listener(development_key, acme).get(ME_URL))

    assert _refusals(log_messages) == ["plugins.service_account.refused plugin=weather reason=development_mode_off"]


def test_the_mode_is_read_on_every_request(development_key, acme, settings):
    settings.PLUGINS_DEV_MODE = True
    assert _through_development_listener(development_key, acme).get(ME_URL).status_code == 200

    settings.PLUGINS_DEV_MODE = False

    _refused(_through_development_listener(development_key, acme).get(ME_URL))


@pytest.mark.usefixtures("development_mode")
def test_a_development_key_still_needs_the_network_secret(development_key, acme):
    client = service_account_client(development_key, acme, network_secret=None, development_listener="1")

    _refused(client.get(ME_URL))


@pytest.mark.usefixtures("development_mode")
@pytest.mark.parametrize("value", ["1", "0"])
def test_a_node_purpose_key_is_refused_on_the_development_listener(acme_key, acme, value, log_messages):
    _refused(_through_development_listener(acme_key, acme, value).get(ME_URL))

    assert _refusals(log_messages) == ["plugins.service_account.refused plugin=weather reason=wrong_listener"]


@pytest.mark.usefixtures("development_mode")
def test_a_node_key_is_refused_on_the_development_listener(plugin_node, service_account_platform):
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"PluginNodeKey {NODE_KEY}",
        HTTP_X_PLUGIN_NETWORK_SECRET=GATEWAY_SECRET,
        HTTP_X_PLUGIN_DEVELOPMENT_LISTENER="1",
    )

    response = client.get(DESIRED_STATE_URL)

    assert response.status_code == 401
    assert response.json()["code"] == "node_not_authenticated"


@pytest.mark.usefixtures("development_mode")
def test_a_revoked_development_key_is_refused_as_revoked_before_the_listener_is_checked(
    development_key, acme, log_messages
):
    PluginServiceAccountKey.objects.filter(purpose=ServiceAccountKeyPurpose.DEVELOPMENT).update(revoked_at=timezone.now())

    _refused(service_account_client(development_key, acme).get(ME_URL))

    assert _refusals(log_messages) == ["plugins.service_account.refused plugin=weather reason=revoked"]


@pytest.mark.usefixtures("development_mode")
def test_a_development_key_of_a_grant_that_holds_no_key_is_refused(development_key, acme):
    PluginGrant.objects.filter(org=acme).update(state=GrantState.INSTALL_FAILED)

    _refused(_through_development_listener(development_key, acme).get(ME_URL))


def test_node_minting_never_touches_development_keys(weather, acme_key, acme):
    development_key = _development_key(weather, acme)
    stored = PluginServiceAccountKey.objects.get(purpose=ServiceAccountKeyPurpose.DEVELOPMENT)

    for _ in range(3):
        ServiceAccountKeyService().mint_for_plugin(weather)

    stored.refresh_from_db()
    assert (stored.expires_at, stored.revoked_at) == (None, None)
    assert stored.key_hash == hashlib.sha256(development_key.encode()).hexdigest()


def test_development_minting_never_touches_node_keys(weather, acme_key, acme):
    node_key = PluginServiceAccountKey.objects.get(purpose=ServiceAccountKeyPurpose.NODE)

    _development_key(weather, acme)
    _development_key(weather, acme)

    node_key.refresh_from_db()
    assert (node_key.expires_at, node_key.revoked_at) == (None, None)
    assert service_account_client(acme_key, acme).get(ME_URL).status_code == 200


@pytest.mark.usefixtures("development_mode")
def test_a_new_development_key_replaces_the_previous_one_at_once(weather, development_key, acme):
    newer = _development_key(weather, acme)

    _refused(_through_development_listener(development_key, acme).get(ME_URL))
    assert _through_development_listener(newer, acme).get(ME_URL).status_code == 200


def test_development_keys_are_minted_for_key_holding_grants_in_a_fixed_number_of_queries(
    weather, superadmin, django_assert_num_queries
):
    organizations = [Organization.objects.create(name=f"development-{index}") for index in range(4)]
    for organization in organizations:
        PluginGrantService().grant(weather.identifier, organization.pk, superadmin)
    PluginGrant.objects.filter(org=organizations[3]).update(state=GrantState.SUSPENDED)
    ServiceAccountKeyService().mint_development_keys(weather)

    with django_assert_num_queries(4 + 2):  # four, inside a savepoint pair
        minted = ServiceAccountKeyService().mint_development_keys(weather)

    assert sorted(key.service_account.grant.org_id for key in minted) == sorted(org.pk for org in organizations[:3])
    assert PluginServiceAccountKey.objects.filter(purpose=ServiceAccountKeyPurpose.DEVELOPMENT, revoked_at__isnull=True).count() == 3


def test_an_account_has_one_current_key_per_purpose(weather, acme_key, acme):
    _development_key(weather, acme)
    account = PluginServiceAccount.objects.get(grant__org=acme)

    for purpose in (ServiceAccountKeyPurpose.NODE, ServiceAccountKeyPurpose.DEVELOPMENT):
        with pytest.raises(IntegrityError), transaction.atomic():
            PluginServiceAccountKey.objects.create(
                service_account=account, purpose=purpose, prefix="esp-xxxxxxxx", key_hash=hashlib.sha256(purpose.encode()).hexdigest()
            )


@pytest.mark.usefixtures("development_mode")
def test_suspending_revokes_development_keys_and_resuming_issues_none(weather, development_key, acme, superadmin):
    grant = PluginGrant.objects.get(plugin=weather, org=acme)

    PluginSuspensionService().suspend("weather", grant.pk, superadmin)

    assert PluginServiceAccountKey.objects.get(purpose=ServiceAccountKeyPurpose.DEVELOPMENT).revoked_at is not None
    PluginSuspensionService().resume("weather", grant.pk, superadmin)
    assert not PluginServiceAccountKey.objects.filter(purpose=ServiceAccountKeyPurpose.DEVELOPMENT, revoked_at__isnull=True).exists()
    _refused(_through_development_listener(development_key, acme).get(ME_URL))
