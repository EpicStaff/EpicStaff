"""Granting plugins to organizations."""

from datetime import datetime, timedelta

import pytest
from django.db import IntegrityError, connection
from django.test.utils import CaptureQueriesContext
from plugins.lifecycle.grant_service import PluginGrantService
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from plugins.models import GrantState, PluginGrant, PluginOwnedResource, PluginServiceAccount
from rbac.models import Organization
from tables.models import Graph

from tests.plugins_tests.conftest import upload_file
from tests.plugins_tests.package_builder import build_package
from tests.plugins_tests.suspension_helpers import secret_row

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


def test_every_grant_response_carries_the_actions_it_allows(superadmin_client, running_plugin, grant_to, acme, beta):
    plugin = running_plugin()
    created = superadmin_client.post(_grants_url(), {"organization_id": acme.id}, format="json").json()
    suspended_at = timezone.now()
    grant_to(plugin, beta, state=GrantState.SUSPENDED)
    PluginGrant.objects.filter(org=beta).update(suspended_at=suspended_at, purge_after=suspended_at + timedelta(days=30))

    listed = {grant["organization"]["id"]: grant for grant in superadmin_client.get(_grants_url()).json()["results"]}

    assert created["allowed_actions"] == ["suspend"]
    assert listed[acme.id]["allowed_actions"] == ["suspend"]
    suspended = listed[beta.id]
    assert (suspended["state"], suspended["allowed_actions"]) == ("suspended", ["resume"])
    assert datetime.fromisoformat(suspended["suspended_at"]) == suspended_at
    assert datetime.fromisoformat(suspended["purge_after"]) == suspended_at + timedelta(days=30)


def test_granting_an_organization_whose_grant_is_suspended_conflicts(superadmin_client, running_plugin, grant_to, acme):
    grant_to(running_plugin(), acme, state=GrantState.SUSPENDED)

    response = superadmin_client.post(_grants_url(), {"organization_id": acme.id}, format="json")

    assert (response.status_code, response.json()["code"]) == (409, "plugin_already_granted")


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



# ---- service accounts, install hooks, owned resources ----


def test_a_grant_shows_its_service_account_install_hook_and_owned_resources(
    weather_backend, superadmin_client, service_account_key, acme
):
    plugin = weather_backend()
    service_account_key(plugin, acme)
    graphs = [Graph.objects.create(name=f"Owned {index}", org=acme) for index in range(2)]
    grant = PluginGrant.objects.get(org=acme)
    PluginOwnedResource.objects.bulk_create(
        PluginOwnedResource(
            org=acme,
            grant=grant,
            plugin_identifier="weather",
            content_type=ContentType.objects.get_for_model(Graph),
            object_id=graph.pk,
        )
        for graph in graphs
    )
    used_at = timezone.now()
    PluginServiceAccount.objects.update(last_used_at=used_at)

    [listed] = superadmin_client.get(_grants_url()).json()["results"]

    assert listed["owned_resource_count"] == 2
    assert listed["install_hook"] is None
    assert listed["service_account"]["created_at"]
    assert datetime.fromisoformat(listed["service_account"]["key_last_used_at"]) == used_at


def test_the_grant_list_takes_a_fixed_number_of_queries(
    weather_backend, superadmin_client, superadmin, django_assert_max_num_queries
):
    plugin = weather_backend(hooks={"install": True})
    for index in range(5):
        PluginGrantService().grant(plugin.identifier, Organization.objects.create(name=f"queries-{index}").pk, superadmin)
    superadmin_client.get(_grants_url())

    with django_assert_max_num_queries(8):
        page = superadmin_client.get(_grants_url()).json()

    assert page["count"] == 5
    assert {grant["install_hook"]["state"] for grant in page["results"]} == {"pending"}


def _own_rows(grant, rows):
    PluginOwnedResource.objects.bulk_create(
        PluginOwnedResource(
            org_id=grant.org_id,
            grant=grant,
            plugin_identifier=grant.plugin.identifier,
            content_type=ContentType.objects.get_for_model(row),
            object_id=row.pk,
        )
        for row in rows
    )


def _owned_queries(captured):
    return [query["sql"] for query in captured.captured_queries if '"plugins_pluginownedresource"' in query["sql"]]


def test_owned_resources_are_counted_for_the_page_only_one_kind_at_a_time(
    running_plugin, superadmin_client, superadmin, acme, beta
):
    plugin = running_plugin()
    gamma = Organization.objects.create(name="Gamma")
    grants = {
        organization.pk: PluginGrantService().grant(plugin.identifier, organization.pk, superadmin)
        for organization in (acme, beta, gamma)
    }
    _own_rows(grants[acme.pk], [Graph.objects.create(name="Acme flow", org=acme), secret_row(acme, "Acme key")])
    _own_rows(grants[beta.pk], [Graph.objects.create(name=f"Beta flow {index}", org=beta) for index in range(3)])
    _own_rows(grants[gamma.pk], [secret_row(gamma, "Gamma key")])
    superadmin_client.get(_grants_url())

    with CaptureQueriesContext(connection) as captured:
        first_page = superadmin_client.get(_grants_url(), {"page_size": 2}).json()

    assert {row["organization"]["name"]: row["owned_resource_count"] for row in first_page["results"]} == {
        acme.name: 2,
        beta.name: 3,
    }
    owned = _owned_queries(captured)
    # The kinds present on the page, then one count per kind with only its own existence check.
    assert len(owned) == 3
    assert [sql.count("EXISTS") for sql in owned[1:]] == [1, 1]
    assert all(str(grants[gamma.pk].pk) not in sql.split(" IN ", 1)[1].split(")", 1)[0] for sql in owned)
    [last] = superadmin_client.get(_grants_url(), {"page_size": 2, "page": 2}).json()["results"]
    assert (last["organization"]["name"], last["owned_resource_count"]) == ("Gamma", 1)


def test_a_grant_read_again_after_a_change_has_its_owned_count(weather_backend, superadmin_client, superadmin, acme):
    plugin = weather_backend()
    grant = PluginGrantService().grant(plugin.identifier, acme.pk, superadmin)
    _own_rows(grant, [Graph.objects.create(name="Owned", org=acme)])

    response = superadmin_client.post(f"/api/admin/plugins/weather/grants/{grant.pk}/suspend/")

    assert (response.status_code, response.json()["owned_resource_count"]) == (200, 1)
