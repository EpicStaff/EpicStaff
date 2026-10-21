"""Granting plugins to organizations."""

import pytest
from django.db import IntegrityError
from plugins.lifecycle.grant_service import PluginGrantService
from plugins.models import GrantState, PluginGrant
from rbac.models import Organization

from tests.plugins_tests.conftest import upload_file
from tests.plugins_tests.package_builder import build_package

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]


def _grants_url(identifier="weather"):
    return f"/api/admin/plugins/{identifier}/grants/"


def test_granting_creates_an_active_grant(superadmin_client, superadmin_user, running_plugin, acme):
    running_plugin()

    response = superadmin_client.post(_grants_url(), {"organization_id": acme.id}, format="json")

    assert response.status_code == 201
    grant = response.json()
    assert grant["plugin_identifier"] == "weather"
    assert grant["organization"] == {"id": acme.id, "name": acme.name}
    assert grant["state"] == "active"
    assert grant["granted_by"] == {"id": superadmin_user.id, "email": superadmin_user.email}
    assert grant["granted_at"]
    assert (grant["suspended_at"], grant["purge_after"], grant["last_hook_error"]) == (None, None, None)
    stored = PluginGrant.objects.get(pk=grant["id"])
    assert (stored.org_id, stored.created_by_id, stored.state) == (acme.id, superadmin_user.id, GrantState.ACTIVE)


def test_the_plugin_count_shows_active_grants(superadmin_client, running_plugin, grant_to, acme, beta):
    plugin = running_plugin()
    grant_to(plugin, acme)
    grant_to(plugin, beta, state=GrantState.SUSPENDED)

    assert superadmin_client.get("/api/admin/plugins/weather/").json()["grant_count"] == 1


def test_granting_twice_conflicts(superadmin_client, running_plugin, acme):
    running_plugin()
    superadmin_client.post(_grants_url(), {"organization_id": acme.id}, format="json")

    response = superadmin_client.post(_grants_url(), {"organization_id": acme.id}, format="json")

    assert response.status_code == 409
    assert response.json()["code"] == "plugin_already_granted"
    assert PluginGrant.objects.count() == 1


def test_granting_to_an_unknown_organization_is_not_found(superadmin_client, running_plugin):
    running_plugin()

    response = superadmin_client.post(_grants_url(), {"organization_id": 999999}, format="json")

    assert response.status_code == 404
    assert response.json()["code"] == "organization_not_found"


def test_granting_to_an_inactive_organization_conflicts(superadmin_client, running_plugin, acme):
    running_plugin()
    Organization.objects.filter(pk=acme.pk).update(is_active=False)

    response = superadmin_client.post(_grants_url(), {"organization_id": acme.id}, format="json")

    assert response.status_code == 409
    assert response.json()["code"] == "organization_inactive"


def test_granting_a_plugin_that_is_not_running_conflicts(superadmin_client, acme):
    superadmin_client.post("/api/admin/plugins/packages/", {"file": upload_file(build_package())}, format="multipart")

    response = superadmin_client.post(_grants_url(), {"organization_id": acme.id}, format="json")

    assert response.status_code == 409
    assert response.json()["code"] == "plugin_not_running"


def test_granting_an_unknown_plugin_is_not_found(superadmin_client, acme):
    response = superadmin_client.post(_grants_url("missing"), {"organization_id": acme.id}, format="json")

    assert response.status_code == 404
    assert response.json()["code"] == "plugin_not_found"


@pytest.mark.parametrize("body", [{}, {"organization_id": "acme"}, {"organization_id": 0}])
def test_a_malformed_body_is_invalid(superadmin_client, running_plugin, body):
    running_plugin()

    response = superadmin_client.post(_grants_url(), body, format="json")

    assert response.status_code == 400
    assert response.json()["code"] == "invalid"


def test_the_grant_list_is_paginated_and_sorted_by_organization_name(superadmin_client, running_plugin, grant_to):
    plugin = running_plugin()
    for name in ("Gamma", "alpha", "Beta"):
        grant_to(plugin, Organization.objects.create(name=f"{name}-grants"))

    first_page = superadmin_client.get(_grants_url(), {"page_size": 2}).json()
    second_page = superadmin_client.get(_grants_url(), {"page_size": 2, "page": 2}).json()

    assert set(first_page) == {"count", "next", "previous", "results"}
    assert first_page["count"] == 3
    assert first_page["previous"] is None and first_page["next"]
    assert [grant["organization"]["name"] for grant in first_page["results"]] == ["alpha-grants", "Beta-grants"]
    assert [grant["organization"]["name"] for grant in second_page["results"]] == ["Gamma-grants"]
    assert second_page["next"] is None


def test_the_grant_list_defaults_to_fifty_per_page(superadmin_client, running_plugin, grant_to):
    plugin = running_plugin()
    for index in range(51):
        grant_to(plugin, Organization.objects.create(name=f"org-{index:02d}"))

    page = superadmin_client.get(_grants_url()).json()

    assert page["count"] == 51
    assert len(page["results"]) == 50


def test_the_grant_list_of_an_unknown_plugin_is_not_found(superadmin_client):
    response = superadmin_client.get(_grants_url("missing"))

    assert response.status_code == 404
    assert response.json()["code"] == "plugin_not_found"


def test_the_grant_list_lists_only_that_plugin_s_grants(superadmin_client, running_plugin, grant_to, acme, beta):
    weather = running_plugin()
    other = running_plugin(id="forecast", name="Forecast")
    grant_to(weather, acme)
    grant_to(other, beta)

    results = superadmin_client.get(_grants_url()).json()["results"]

    assert [grant["organization"]["id"] for grant in results] == [acme.id]


def test_an_integrity_error_other_than_a_repeated_grant_surfaces(running_plugin, superadmin, acme, monkeypatch):
    running_plugin()

    def fail(**fields):
        raise IntegrityError("a different constraint")

    monkeypatch.setattr(PluginGrant.objects, "create", fail)

    with pytest.raises(IntegrityError, match="a different constraint"):
        PluginGrantService().grant("weather", acme.id, superadmin)

