"""A service account may do exactly what its plugin declared, in its own organization."""

import copy

import pytest
from django.urls import reverse
from plugins.access.declared_access import NON_DECLARABLE_RESOURCE_TYPES
from plugins.exceptions import InvalidPluginError
from rbac.models import ApiKey
from rest_framework.test import APIClient
from tables.import_export.enums import EntityType
from tables.import_export.registry import entity_registry
from tables.import_export.services.export_service import ExportService
from tables.models import Graph, LLMConfig, Secret, Session
from tables.models.graph_models import ScheduleTriggerNode

from tests.helpers import data_to_json_file
from tests.plugins_tests.conftest import WEATHER_ACCESS, mark_running, service_account_client, upload_file
from tests.plugins_tests.package_builder import backend_manifest, build_package
from tests.plugins_tests.service_account_helpers import runnable_graph

pytestmark = [pytest.mark.django_db]

WITHOUT_USE = [
    {"resource_type": "flows", "actions": ["read", "create", "update"], "reason": "Edits flows."},
    {"resource_type": "files", "actions": ["read"], "reason": "Reads files."},
]


@pytest.fixture
def weather_client_without_use(backend_plugin, service_account_platform, service_account_key, acme):
    plugin = mark_running(backend_plugin(id="forecast", name="Forecast", access=WITHOUT_USE))
    return service_account_client(service_account_key(plugin, acme), acme)


def _assert_denied(response, code="permission_denied"):
    assert response.status_code == 403, response.content
    assert response.json()["code"] == code


# ---- flows ----


def test_a_declared_create_succeeds_in_the_plugin_s_organization(weather_client, acme):
    response = weather_client.post("/api/graphs/", {"name": "Weather forecast"}, format="json")

    assert response.status_code == 201
    assert Graph.objects.get(pk=response.json()["id"]).org_id == acme.pk


def test_an_undeclared_action_is_refused(weather_client, acme):
    graph = Graph.objects.create(name="Someone's flow", org=acme)

    _assert_denied(weather_client.delete(f"/api/graphs/{graph.pk}/"))
    _assert_denied(weather_client.post("/api/agent-definitions/", {"name": "Agent"}, format="json"))
    assert Graph.objects.filter(pk=graph.pk).exists()


def test_another_organization_s_row_is_not_found(weather_client, beta):
    graph = Graph.objects.create(name="Beta's flow", org=beta)

    assert weather_client.get(f"/api/graphs/{graph.pk}/").status_code == 404


def test_running_a_flow_needs_flows_use(weather_client, weather_client_without_use, acme, redis_client_mock):
    graph = runnable_graph("forecast", acme)
    body = {"graph_id": graph.pk, "variables": {}}

    _assert_denied(weather_client_without_use.post(reverse("run-session"), body, format="json"))
    assert not Session.objects.exists()

    response = weather_client.post(reverse("run-session"), body, format="json")

    assert response.status_code == 201, response.content
    assert Session.objects.get(pk=response.json()["session_id"]).graph_id == graph.pk


def test_a_schedule_trigger_needs_flows_use(weather_client, weather_client_without_use, acme):
    graph = Graph.objects.create(name="Daily forecast", org=acme)
    body = {"graph": graph.pk, "node_name": "Daily"}

    _assert_denied(
        weather_client_without_use.post("/api/schedule-trigger-nodes/", body, format="json"),
        code="trigger_nodes_require_use_permission",
    )
    assert not ScheduleTriggerNode.objects.exists()

    assert weather_client.post("/api/schedule-trigger-nodes/", body, format="json").status_code == 201


def test_importing_a_flow_with_a_trigger_needs_flows_use(weather_client_without_use, acme):
    source = Graph.objects.create(name="Triggered", org=acme)
    ScheduleTriggerNode.objects.create(graph=source, node_name="Hourly")
    export_data = ExportService(entity_registry).export_entities(EntityType.GRAPH, [source.pk], org_id=acme.pk)

    response = weather_client_without_use.post(
        reverse("graphs-import-entity"),
        {"file": data_to_json_file(data=export_data, filename="flow.json")},
        format="multipart",
    )

    _assert_denied(response, code="flow_with_trigger_nodes_requires_use_permission")


# ---- secrets and LLM configs ----


def test_a_secret_is_created_and_its_value_never_returned(weather_client, acme):
    response = weather_client.post("/api/secrets/", {"name": "Weather · LLM key", "value": "sk-weather-123"}, format="json")

    assert response.status_code == 201, response.content
    assert "value" not in response.json()
    assert "sk-weather-123" not in response.content.decode()
    assert Secret.objects.get(pk=response.json()["id"]).org_id == acme.pk
    listed = weather_client.get("/api/secrets/")
    assert "sk-weather-123" not in listed.content.decode()


def test_a_personal_api_key_is_still_refused_on_secrets(admin_acme, acme, issue_api_key):
    raw_key, _ = issue_api_key(user=admin_acme)
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_key, HTTP_X_ORGANIZATION_ID=str(acme.pk))

    _assert_denied(client.get("/api/secrets/"))


def test_an_llm_config_is_created(weather_client, acme):
    response = weather_client.post("/api/llm-configs/", {"custom_name": "Weather summaries"}, format="json")

    assert response.status_code == 201, response.content
    assert LLMConfig.objects.get(pk=response.json()["id"]).org_id == acme.pk


# ---- surfaces a service account never reaches ----


def test_key_management_purges_and_the_admin_surface_are_refused(weather_client, acme):
    graph = Graph.objects.create(name="Binned", org=acme)

    assert weather_client.get("/api/profile/api-keys/").status_code == 401
    assert weather_client.post("/api/profile/api-keys/", {"name": "k"}, format="json").status_code == 401
    assert weather_client.get("/api/admin/organizations/").status_code == 401
    assert weather_client.delete(f"/api/graphs/{graph.pk}/purge/").status_code == 403
    assert weather_client.post("/api/recycle-bin/empty/", {}, format="json").status_code == 403
    assert weather_client.get("/api/admin/plugins/").status_code == 401
    assert not ApiKey.objects.exists()


# ---- upload ----


@pytest.mark.parametrize("resource_type", sorted(NON_DECLARABLE_RESOURCE_TYPES))
def test_a_non_declarable_resource_type_is_refused_at_upload(installation, superadmin, resource_type):
    manifest = backend_manifest(access=[{"resource_type": resource_type, "actions": ["read"], "reason": "Needed."}])
    data = build_package(manifest=copy.deepcopy(manifest))

    with pytest.raises(InvalidPluginError) as raised:
        installation.upload(upload_file(data), len(data), superadmin)

    assert raised.value.errors == [
        {"loc": "manifest.access[0].resource_type", "message": f"'{resource_type}' cannot be declared by a plugin"}
    ]


def test_weather_s_access_is_accepted_at_upload(installation, superadmin):
    data = build_package(manifest=backend_manifest(access=copy.deepcopy(WEATHER_ACCESS)))

    package = installation.upload(upload_file(data), len(data), superadmin)

    assert [declaration["resource_type"] for declaration in package.manifest["access"]] == [
        "flows",
        "files",
        "secrets",
        "llm_configs",
    ]
