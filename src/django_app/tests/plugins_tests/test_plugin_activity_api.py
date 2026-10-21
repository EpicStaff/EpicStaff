"""Plugin activity: what is recorded, and who reads it where."""

import pytest
from plugins.models import Plugin, PluginActivityEvent
from tables.models import Graph

from tests.plugins_tests.conftest import WEATHER_ACCESS, service_account_client, upload_file
from tests.plugins_tests.package_builder import backend_manifest, build_package

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("service_account_platform")]

ACTIVITY_URL = "/api/plugins/activity/"
SERVICE_ACCOUNTS_URL = "/api/plugins/service-accounts/"
ADMIN_ACTIVITY_URL = "/api/admin/plugins/weather/activity/"


@pytest.fixture
def weather(weather_backend):
    return weather_backend()


@pytest.fixture
def client(weather, service_account_key, acme):
    return service_account_client(service_account_key(weather, acme), acme)


@pytest.fixture
def org_admin_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.pk))
    return client


def _api_requests():
    return list(PluginActivityEvent.objects.filter(action="api_request").order_by("pk"))


# ---- what a service account's request records ----


def test_a_successful_write_is_recorded_with_its_target(client, acme):
    response = client.post("/api/graphs/", {"name": "Weather forecast"}, format="json")

    [event] = _api_requests()
    assert (event.plugin_identifier, event.organization_id) == ("weather", acme.pk)
    assert (event.actor_kind, event.actor_label, event.actor_user_id) == ("plugin", "Weather (plugin)", None)
    assert (event.on_behalf_of_user_id, event.on_behalf_of_label) == (None, None)
    assert (event.request_method, event.request_path, event.response_status) == ("POST", "/api/graphs/", 201)
    assert "graphs" in event.request_route
    assert (event.target_resource_type, event.target_id, event.target_label) == (
        "flows",
        str(response.json()["id"]),
        "Weather forecast",
    )
    assert event.detail == {"created_count": 1}


def test_a_write_to_an_existing_row_names_it_from_the_url(client, acme):
    graph = Graph.objects.create(name="Existing", org=acme)

    body = {"description": "Updated", "save_version": graph.save_version}
    assert client.patch(f"/api/graphs/{graph.pk}/", body, format="json").status_code == 200

    [event] = _api_requests()
    assert (event.target_id, event.target_label, event.detail) == (str(graph.pk), "Existing", {"created_count": 0})


def test_reads_failures_and_runtime_calls_are_not_recorded(client, member_only):
    client.get("/api/graphs/")
    client.post("/api/graphs/", {}, format="json")
    client.post("/api/plugin-runtime/people/lookup/", {"user_ids": [member_only.pk]}, format="json")

    assert _api_requests() == []


def test_the_query_string_is_never_recorded(client):
    client.post("/api/graphs/?token=secret-value", {"name": "With a query"}, format="json")

    [event] = _api_requests()
    assert event.request_path == "/api/graphs/"


def test_a_person_s_write_is_not_recorded(org_admin_client):
    org_admin_client.post("/api/graphs/", {"name": "Olga's"}, format="json")

    assert _api_requests() == []


def test_a_failure_to_record_never_changes_the_response(client, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("database gone")

    monkeypatch.setattr(PluginActivityEvent.objects, "create", fail)

    response = client.post("/api/graphs/", {"name": "Still created"}, format="json")

    assert response.status_code == 201
    assert Graph.objects.filter(name="Still created").exists()


# ---- lifecycle events ----


def test_approving_a_package_is_a_deployment_wide_event(installation, superadmin, plugin_node):
    data = build_package(manifest=backend_manifest(access=WEATHER_ACCESS))
    package = installation.upload(upload_file(data), len(data), superadmin)

    installation.approve(package.pk, superadmin, untrusted_acknowledged=True)

    event = PluginActivityEvent.objects.get(action="package_approved")
    assert (event.organization_id, event.actor_kind, event.actor_user_id, event.actor_label) == (
        None,
        "superadmin",
        superadmin.pk,
        superadmin.email,
    )
    assert event.detail == {"version": "0.2.0", "trust": "untrusted"}


def test_granting_is_an_event_of_the_organization(weather, superadmin_client, superadmin_user, beta):
    superadmin_client.post("/api/admin/plugins/weather/grants/", {"organization_id": beta.pk}, format="json")

    event = PluginActivityEvent.objects.get(action="grant_created")
    assert (event.organization_id, event.actor_user_id) == (beta.pk, superadmin_user.pk)


def test_settings_limits_and_restart_are_deployment_wide_events_without_values(weather, superadmin_client):
    superadmin_client.patch(
        "/api/admin/plugins/weather/settings/",
        {"values": {"units": "imperial", "forecast_api_token": "token-123456789"}},
        format="json",
    )
    superadmin_client.patch("/api/admin/plugins/weather/limits/", {"overrides": {"memory_mb": 128}}, format="json")
    superadmin_client.post("/api/admin/plugins/weather/restart/")

    settings_event = PluginActivityEvent.objects.get(action="settings_changed")
    assert settings_event.detail == {"keys": ["forecast_api_token", "units"]}
    assert "token-123456789" not in str(settings_event.detail)
    assert PluginActivityEvent.objects.get(action="limits_changed").detail == {"overrides": {"memory_mb": 128}}
    assert PluginActivityEvent.objects.get(action="restarted").detail == {"restart_generation": 1}
    assert set(
        PluginActivityEvent.objects.filter(action__in=["settings_changed", "limits_changed", "restarted"]).values_list(
            "organization_id", flat=True
        )
    ) == {None}


# ---- the organization's endpoints ----


def test_an_org_admin_sees_the_organization_s_events_newest_first_never_deployment_wide_ones(
    client, org_admin_client, acme, beta, weather, superadmin_client
):
    client.post("/api/graphs/", {"name": "First"}, format="json")
    client.post("/api/graphs/", {"name": "Second"}, format="json")
    superadmin_client.patch("/api/admin/plugins/weather/limits/", {"overrides": {"memory_mb": 128}}, format="json")
    PluginActivityEvent.objects.create(
        plugin_identifier="weather", organization_id=beta.pk, actor_kind="platform", actor_label="Platform", action="grant_created"
    )

    body = org_admin_client.get(ACTIVITY_URL).json()

    assert set(body) == {"count", "next", "previous", "results"}
    assert [event["target"]["label"] for event in body["results"] if event["action"] == "api_request"] == ["Second", "First"]
    assert {event["organization"]["id"] for event in body["results"]} == {acme.pk}
    assert all(event["action"] != "limits_changed" for event in body["results"])


def test_an_event_has_the_documented_shape(client, org_admin_client, acme, member_only, weather, service_account_key):
    on_behalf = service_account_client(service_account_key(weather, acme), acme, on_behalf_of=member_only.pk)
    on_behalf.post("/api/graphs/", {"name": "For Ada"}, format="json")
    event = PluginActivityEvent.objects.get(action="api_request")

    body = org_admin_client.get(f"{ACTIVITY_URL}{event.pk}/").json()

    assert body == {
        "id": event.pk,
        "created_at": body["created_at"],
        "plugin": {"identifier": "weather", "name": "Weather"},
        "organization": {"id": acme.pk, "name": acme.name},
        "actor": {"kind": "plugin", "label": "Weather (plugin)"},
        "on_behalf_of": {"user_id": member_only.pk, "label": member_only.email},
        "action": "api_request",
        "request": {"method": "POST", "path": "/api/graphs/", "route": event.request_route, "status": 201},
        "target": {"resource_type": "flows", "id": event.target_id, "label": "For Ada"},
        "detail": {"created_count": 1},
    }


def test_the_list_filters_by_plugin_and_action_and_pages(client, org_admin_client, acme):
    for index in range(3):
        client.post("/api/graphs/", {"name": f"Flow {index}"}, format="json")

    assert org_admin_client.get(ACTIVITY_URL, {"plugin": "other"}).json()["count"] == 0
    assert org_admin_client.get(ACTIVITY_URL, {"action": "api_request"}).json()["count"] == 3
    page = org_admin_client.get(ACTIVITY_URL, {"action": "api_request", "page_size": 2}).json()
    assert (len(page["results"]), page["next"] is not None) == (2, True)
    assert org_admin_client.get(ACTIVITY_URL, {"action": "nonsense"}).status_code == 400


def test_another_organization_s_event_is_not_found(org_admin_client, beta):
    event = PluginActivityEvent.objects.create(
        plugin_identifier="weather", organization_id=beta.pk, actor_kind="platform", actor_label="Platform", action="grant_created"
    )

    response = org_admin_client.get(f"{ACTIVITY_URL}{event.pk}/")

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_a_member_without_audit_read_is_refused(client_as, member_only, acme):
    client = client_as(member_only)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.pk))

    for url in (ACTIVITY_URL, SERVICE_ACCOUNTS_URL):
        response = client.get(url)
        assert response.status_code == 403
        assert response.json()["code"] == "permission_denied"


def test_a_non_member_is_refused(client_as, member_only, beta):
    client = client_as(member_only)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(beta.pk))

    assert client.get(ACTIVITY_URL).status_code == 403


def test_a_service_account_cannot_read_activity(client):
    assert client.get(ACTIVITY_URL).status_code == 401
    assert client.get(SERVICE_ACCOUNTS_URL).status_code == 401


def test_the_service_accounts_list_shows_each_plugin_acting_here_with_its_declared_access(
    client, org_admin_client, weather_backend, running_plugin, grant_to, acme, beta, superadmin
):
    client.get("/api/plugin-runtime/me/")
    frontend_only = running_plugin(id="notes", name="Notes")
    grant_to(frontend_only, acme)

    body = org_admin_client.get(SERVICE_ACCOUNTS_URL).json()

    assert [account["plugin"]["identifier"] for account in body] == ["weather"]
    [account] = body
    assert account["plugin"] == {
        "identifier": "weather",
        "name": "Weather",
        "icon_url": f"/api/plugin-public/weather/icon/?v={Plugin.objects.get(identifier='weather').current_package.version}",
    }
    assert account["grant_state"] == "active"
    assert account["created_at"] and account["key_last_used_at"]
    assert [row["resource_type"] for row in account["access"]] == ["flows", "files", "secrets", "llm_configs"]
    assert account["access"][0] == {
        "resource_type": "flows",
        "resource_label": "Flows",
        "actions": ["read", "create", "update", "use"],
        "reason": WEATHER_ACCESS[0]["reason"],
    }


def test_the_service_accounts_list_shows_only_the_active_organization_s(client, client_as, make_member, role_org_admin, beta):
    admin_beta = make_member(beta, role_org_admin, "admin-beta-sa@example.com")
    beta_client = client_as(admin_beta)
    beta_client.credentials(HTTP_X_ORGANIZATION_ID=str(beta.pk))

    assert beta_client.get(SERVICE_ACCOUNTS_URL).json() == []


# ---- the admin endpoint ----


def test_a_superadmin_sees_every_organization_s_and_the_deployment_wide_events(
    client, weather, superadmin_client, beta, acme, service_account_key
):
    client.post("/api/graphs/", {"name": "In Acme"}, format="json")
    superadmin_client.post("/api/admin/plugins/weather/grants/", {"organization_id": beta.pk}, format="json")
    superadmin_client.post("/api/admin/plugins/weather/restart/")

    body = superadmin_client.get(ADMIN_ACTIVITY_URL).json()

    organizations = {event["organization"]["id"] if event["organization"] else None for event in body["results"]}
    assert organizations == {acme.pk, beta.pk, None}
    filtered = superadmin_client.get(ADMIN_ACTIVITY_URL, {"organization_id": beta.pk, "action": "grant_created"}).json()
    assert [event["organization"]["id"] for event in filtered["results"]] == [beta.pk]


def test_the_admin_endpoint_is_for_superadmins_only(org_admin_client, client):
    assert org_admin_client.get(ADMIN_ACTIVITY_URL).status_code == 403
    assert client.get(ADMIN_ACTIVITY_URL).status_code == 401


def test_an_unknown_plugin_without_events_is_not_found(superadmin_client, service_account_platform):
    response = superadmin_client.get("/api/admin/plugins/missing/activity/")

    assert response.status_code == 404
    assert response.json()["code"] == "plugin_not_found"


def test_events_outlive_the_plugin_row(client, superadmin_client, weather):
    client.post("/api/graphs/", {"name": "Before removal"}, format="json")

    Plugin.objects.filter(pk=weather.pk).delete()

    body = superadmin_client.get(ADMIN_ACTIVITY_URL).json()
    assert body["count"] >= 2
    assert {event["plugin"]["name"] for event in body["results"]} == {None}
