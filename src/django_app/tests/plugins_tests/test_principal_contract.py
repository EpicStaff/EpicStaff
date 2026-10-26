"""The service-account principal is pinned to one organization and never passes for a user."""

import pytest
from plugins.identity.service_account_authentication import PluginServiceAccountAuthentication
from rbac.access.principals import PinnedOrgPrincipal, acting_person, is_plugin_credential
from rbac.authorship.policy import resolve_author
from rbac.exceptions import OrgMembershipRequiredError
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from tests.plugins_tests.conftest import GATEWAY_SECRET

pytestmark = [pytest.mark.django_db]


def _authenticated(raw_key, **extra):
    request = Request(
        APIRequestFactory().get(
            "/api/graphs/",
            HTTP_AUTHORIZATION=f"PluginKey {raw_key}",
            HTTP_X_PLUGIN_NETWORK_SECRET=GATEWAY_SECRET,
            **extra,
        ),
        authenticators=[PluginServiceAccountAuthentication()],
    )
    return request, request.user


@pytest.fixture
def principal_request(weather_backend, service_account_key, acme):
    plugin = weather_backend()
    return _authenticated(service_account_key(plugin, acme))


@pytest.mark.parametrize("attribute", ["id", "pk", "email", "username", "is_active"])
def test_the_principal_has_no_user_attribute(principal_request, attribute):
    _, principal = principal_request

    assert not hasattr(principal, attribute)


def test_the_principal_names_its_plugin_organization_and_rate_bucket(principal_request, acme):
    _, principal = principal_request

    assert principal.pinned_org_id == acme.pk
    assert principal.plugin_identifier == "weather"
    assert principal.display_name == "Weather (plugin)"
    assert principal.rate_limit_key == f"plugin-service-account:{principal.service_account_id}"
    assert principal.person is None
    assert str(principal) == f"plugin weather (org {acme.pk})"
    assert (principal.is_authenticated, principal.is_anonymous, principal.is_superadmin) == (True, False, False)


def test_the_principal_is_a_pinned_org_principal_and_a_plugin_credential(principal_request):
    request, principal = principal_request

    assert isinstance(principal, PinnedOrgPrincipal)
    assert request.auth.is_plugin_credential is True
    assert principal.is_plugin_credential is True
    assert is_plugin_credential(request)


def test_the_principal_is_never_an_author(principal_request):
    _, principal = principal_request

    assert resolve_author(principal) is None
    assert acting_person(principal) is None


def test_the_principal_acts_for_the_person_it_was_given(weather_backend, service_account_key, acme, member_only):
    plugin = weather_backend()

    _, principal = _authenticated(service_account_key(plugin, acme), HTTP_X_EPICSTAFF_ON_BEHALF_OF=str(member_only.pk))

    assert principal.person == member_only
    assert acting_person(principal) == member_only
    assert resolve_author(principal) is None


def test_the_principal_holds_the_declared_access_in_its_organization_only(principal_request, acme, beta):
    _, principal = principal_request

    permissions = principal.resolve_effective_permissions(acme.pk)

    assert permissions.is_superadmin is False
    assert permissions.role is None
    assert permissions.to_action_codes()["flows"] == ["create", "read", "update", "use"]
    assert permissions.to_action_codes()["files"] == ["create", "read"]
    assert permissions.to_action_codes()["secrets"] == ["create", "read", "use"]
    assert permissions.to_action_codes()["agents"] == []
    with pytest.raises(OrgMembershipRequiredError):
        principal.resolve_effective_permissions(beta.pk)
