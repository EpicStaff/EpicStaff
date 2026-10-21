"""Which rows a plugin's service account owns, and the guards that keep every write path covered."""

import ast
from pathlib import Path

import pytest
from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.db import connection, models, transaction
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from plugins.identity.service_account_authentication import PluginServiceAccountAuthentication
from plugins.models import PluginGrant, PluginOwnedResource
from plugins.ownership import request_scope
from plugins.ownership.ownership_recorder import EXTRA_OWNABLE_MODELS, ownable_models
from rbac.models import Organization
from rbac.models.org_scoped import OrgScopedModel
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory
from tables.import_export.enums import EntityType
from tables.import_export.registry import entity_registry
from tables.import_export.services.export_service import ExportService
from tables.models import Graph, KeyValueTable, LLMConfig, Secret, StorageFile
from tables.models.graph_models import StartNode
from tables.services.storage_service.db_sync import StorageFileSync

from tests.helpers import data_to_json_file
from tests.plugins_tests.conftest import GATEWAY_SECRET, service_account_client

pytestmark = [pytest.mark.django_db]

DJANGO_APP = Path(__file__).resolve().parents[2]
OWNER_ACCESS = [
    {"resource_type": "flows", "actions": ["read", "create", "update"], "reason": "Flows."},
    {"resource_type": "secrets", "actions": ["read", "create"], "reason": "Secrets."},
    {"resource_type": "llm_configs", "actions": ["read", "create"], "reason": "Configs."},
    {"resource_type": "key_value_tables", "actions": ["read", "create"], "reason": "Tables."},
    {"resource_type": "files", "actions": ["read", "create"], "reason": "Files."},
]

# Every concrete organization-owned model that is not an ownable root, and why.
NOT_OWNABLE_MODELS = {
    "plugins.PluginGrant": "the plugin platform's own row, created by a SuperAdmin",
    "tables.Agent": "legacy crew model: no endpoint creates one any more",
    "tables.Crew": "legacy crew model: no endpoint creates one any more",
    "tables.AuditFilterPreset": "a person's own saved filter; refused to plugin credentials",
    "tables.DefaultModels": "the organization's one settings row, created with the organization",
    "tables.Label": "a node of a shared label tree: the organization's own labels and flows hang under it, as under a storage folder",
    "tables.PythonCodeResult": "a run's result, written by the sandbox callback; its key is text",
    "tables.PythonCodeToolConfig": "a configuration of one Python tool, deleted with the tool: not a root",
    "tables.RealtimeSessionItem": "conversation data the realtime service writes",
}
# Each `bulk_create` of an ownable root outside tests, by file and function, and how its rows
# get owned (or why they never need to be).
BULK_CREATE_SITES = {
    "tables/services/storage_service/db_sync.py::StorageFileSync.on_bulk_upload": "sends rows_bulk_created for the files it inserts; its folder insert makes folders only, which are never owned",
    "tables/services/storage_service/reconciler.py::StorageReconciler.reconcile_tree": "background sync from the storage backend, never under a service account",
}


@pytest.fixture
def owner(weather_backend, service_account_key, acme):
    plugin = weather_backend(access=OWNER_ACCESS)
    return service_account_client(service_account_key(plugin, acme), acme)


@pytest.fixture
def owner_for_member(weather_backend, service_account_key, acme, member_only):
    plugin = weather_backend(access=OWNER_ACCESS)
    return service_account_client(service_account_key(plugin, acme), acme, on_behalf_of=member_only.pk)


def _owned(model, pk):
    return PluginOwnedResource.objects.filter(content_type=ContentType.objects.get_for_model(model), object_id=pk).first()


# ---- what is owned ----


@pytest.mark.parametrize(
    ("url", "body", "model"),
    [
        ("/api/graphs/", {"name": "Weather forecast"}, Graph),
        ("/api/secrets/", {"name": "Weather · LLM key", "value": "sk-1"}, Secret),
        ("/api/llm-configs/", {"custom_name": "Weather summaries"}, LLMConfig),
        ("/api/key-value-tables/", {"name": "weather_cache"}, KeyValueTable),
    ],
    ids=["flow", "secret", "llm-config", "key-value-table"],
)
def test_a_root_the_service_account_creates_is_owned(owner, acme, url, body, model):
    response = owner.post(url, body, format="json")

    assert response.status_code == 201, response.content
    owned = _owned(model, response.json()["id"])
    assert owned is not None
    assert (owned.org_id, owned.plugin_identifier, owned.on_behalf_of_id) == (acme.pk, "weather", None)
    assert owned.grant == PluginGrant.objects.get(org=acme)


def test_a_root_created_on_behalf_of_a_person_records_the_person(owner_for_member, member_only):
    response = owner_for_member.post("/api/graphs/", {"name": "For Ada"}, format="json")

    assert _owned(Graph, response.json()["id"]).on_behalf_of_id == member_only.pk


def test_child_rows_are_not_owned(owner, acme):
    graph_id = owner.post("/api/graphs/", {"name": "With a start"}, format="json").json()["id"]
    start = StartNode.objects.create(graph_id=graph_id, variables={})

    assert _owned(StartNode, start.pk) is None
    assert PluginOwnedResource.objects.count() == 1


def test_rows_a_person_creates_are_not_owned(client_as, admin_acme, acme, owner):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.pk))

    response = client.post("/api/graphs/", {"name": "Olga's flow"}, format="json")

    assert response.status_code == 201
    assert _owned(Graph, response.json()["id"]) is None


def test_a_graph_the_service_account_copies_is_owned_and_one_a_person_copies_is_not(owner, client_as, admin_acme, acme):
    source = Graph.objects.create(name="Source", org=acme)
    person = client_as(admin_acme)
    person.credentials(HTTP_X_ORGANIZATION_ID=str(acme.pk))

    by_plugin = owner.post(reverse("graphs-copy", args=[source.pk]), {}, format="json")
    by_person = person.post(reverse("graphs-copy", args=[source.pk]), {}, format="json")

    assert by_plugin.status_code == 201, by_plugin.content
    assert _owned(Graph, by_plugin.json()["id"]) is not None
    assert _owned(Graph, by_person.json()["id"]) is None


def test_a_graph_the_service_account_imports_is_owned(owner, acme):
    source = Graph.objects.create(name="Imported forecast", org=acme)
    export_data = ExportService(entity_registry).export_entities(EntityType.GRAPH, [source.pk], org_id=acme.pk)

    response = owner.post(
        reverse("graphs-import-entity"),
        {"file": data_to_json_file(data=export_data, filename="flow.json")},
        format="multipart",
    )

    assert response.status_code == 200, response.content
    imported = Graph.objects.filter(org=acme).exclude(pk=source.pk)
    assert imported.count() == 1
    assert _owned(Graph, imported.get().pk) is not None


def test_bulk_uploaded_files_are_owned_and_their_folders_are_not(weather_backend, service_account_key, acme):
    plugin = weather_backend(access=OWNER_ACCESS)
    request = Request(
        APIRequestFactory().post(
            "/api/storage/upload/",
            HTTP_AUTHORIZATION=f"PluginKey {service_account_key(plugin, acme)}",
            HTTP_X_PLUGIN_NETWORK_SECRET=GATEWAY_SECRET,
        ),
        authenticators=[PluginServiceAccountAuthentication()],
    )
    assert request.user.plugin_identifier == "weather"

    StorageFileSync.on_bulk_upload(acme.pk, [("bundle/a.txt", 1), ("bundle/sub/b.txt", 2)], user=request.user)

    files = StorageFile.objects.filter(org=acme, item_type="file")
    folders = StorageFile.objects.filter(org=acme, item_type="folder")
    assert sorted(_owned(StorageFile, row.pk) is not None for row in files) == [True, True]
    assert folders.exists()
    assert all(_owned(StorageFile, row.pk) is None for row in folders)


def test_a_rolled_back_create_leaves_no_ownership(weather_backend, service_account_key, acme):
    plugin = weather_backend(access=OWNER_ACCESS)
    request = Request(
        APIRequestFactory().get(
            "/",
            HTTP_AUTHORIZATION=f"PluginKey {service_account_key(plugin, acme)}",
            HTTP_X_PLUGIN_NETWORK_SECRET=GATEWAY_SECRET,
        ),
        authenticators=[PluginServiceAccountAuthentication()],
    )
    assert request.user.is_plugin_credential

    with pytest.raises(RuntimeError), transaction.atomic():
        Graph.objects.create(name="Rolled back", org=acme)
        assert PluginOwnedResource.objects.count() == 1
        raise RuntimeError("roll back")

    assert not PluginOwnedResource.objects.exists()


def test_purging_a_root_deletes_its_ownership(owner, acme):
    graph = Graph.objects.get(pk=owner.post("/api/graphs/", {"name": "Short-lived"}, format="json").json()["id"])

    graph.delete()
    assert _owned(Graph, graph.pk) is not None
    Graph.all_objects.get(pk=graph.pk).purge()

    assert _owned(Graph, graph.pk) is None


def _own_files_as_the_plugin(plugin, service_account_key, organization, count):
    request = Request(
        APIRequestFactory().post(
            "/",
            HTTP_AUTHORIZATION=f"PluginKey {service_account_key(plugin, organization)}",
            HTTP_X_PLUGIN_NETWORK_SECRET=GATEWAY_SECRET,
        ),
        authenticators=[PluginServiceAccountAuthentication()],
    )
    StorageFileSync.on_bulk_upload(organization.pk, [(f"many/{index}.txt", 1) for index in range(count)], user=request.user)
    request_scope._current_scope.set(None)


def test_deleting_owned_rows_by_queryset_costs_the_same_for_one_or_many(
    weather_backend, service_account_key, acme, beta
):
    plugin = weather_backend(access=OWNER_ACCESS)
    _own_files_as_the_plugin(plugin, service_account_key, acme, 1)
    _own_files_as_the_plugin(plugin, service_account_key, beta, 5)
    assert PluginOwnedResource.objects.count() == 6

    def delete_files(organization):
        with CaptureQueriesContext(connection) as captured:
            StorageFile.all_objects.filter(org=organization, item_type="file").delete()
        return len(captured.captured_queries)

    assert delete_files(acme) == delete_files(beta)
    assert not PluginOwnedResource.objects.exists()


def test_deleting_the_organization_takes_its_ownership_rows(owner, acme):
    owner.post("/api/graphs/", {"name": "Goes with the org"}, format="json")

    Organization.objects.filter(pk=acme.pk).delete()

    assert not PluginOwnedResource.objects.exists()


# ---- the guards ----


def _organization_owned_models():
    for model in apps.get_models():
        if model._meta.abstract or model._meta.proxy:
            continue
        agents_with_org = model._meta.app_label == "agents" and any(
            getattr(field, "related_model", None) is Organization for field in model._meta.fields
        )
        if issubclass(model, OrgScopedModel) or agents_with_org:
            yield model


def test_every_organization_owned_model_is_ownable_or_named_as_not_ownable():
    ownable = {model._meta.label for model in ownable_models()}
    unclassified = sorted(
        model._meta.label
        for model in _organization_owned_models()
        if model._meta.label not in ownable and model._meta.label not in NOT_OWNABLE_MODELS
    )

    assert unclassified == [], f"classify these models as ownable or not ownable: {unclassified}"
    assert ownable.isdisjoint(NOT_OWNABLE_MODELS)
    assert all(apps.get_model(label) for label in NOT_OWNABLE_MODELS)


def _cascade_reachable_from(model):
    reachable, frontier = set(), [model]
    while frontier:
        current = frontier.pop()
        for relation in current._meta.related_objects:
            if getattr(relation.on_delete, "__name__", "") != "CASCADE":
                continue
            if relation.related_model not in reachable:
                reachable.add(relation.related_model)
                frontier.append(relation.related_model)
    return reachable


def test_no_ownable_root_cascades_from_a_row_of_its_own_model():
    # Ownership rows of a deleted queryset go in one query, which covers only the rows the
    # queryset matches; a root deleted by cascade from a row of its own model would be missed.
    assert sorted(model._meta.label for model in ownable_models() if model in _cascade_reachable_from(model)) == []


def test_every_ownable_root_has_an_integer_key():
    assert all(
        isinstance(model._meta.pk, (models.AutoField, models.BigAutoField, models.IntegerField))
        for model in ownable_models()
    )
    assert {apps.get_model(label) for label in EXTRA_OWNABLE_MODELS} <= set(ownable_models())


class _BulkCreateFinder(ast.NodeVisitor):
    """`<Model>.<manager>.bulk_create(` calls, by enclosing function (`Class.method`)."""

    def __init__(self, model_names: set[str]):
        self._model_names = model_names
        self._scope: list[str] = []
        self.sites: list[str] = []

    def visit_ClassDef(self, node):
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_FunctionDef(self, node):
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node):
        function = node.func
        if (
            isinstance(function, ast.Attribute)
            and function.attr == "bulk_create"
            and isinstance(function.value, ast.Attribute)
            and isinstance(function.value.value, ast.Name)
            and function.value.value.id in self._model_names
        ):
            self.sites.append(".".join(self._scope) or "<module>")
        self.generic_visit(node)


def _bulk_create_sites_of_ownable_roots() -> set[str]:
    model_names = {model.__name__ for model in ownable_models()}
    sites = set()
    for app in ("tables", "agents"):
        for path in sorted((DJANGO_APP / app).rglob("*.py")):
            relative = path.relative_to(DJANGO_APP).as_posix()
            if "/migrations/" in relative or "/tests/" in relative:
                continue
            finder = _BulkCreateFinder(model_names)
            finder.visit(ast.parse(path.read_text(encoding="utf-8")))
            sites.update(f"{relative}::{site}" for site in finder.sites)
    return sites


def test_every_bulk_create_of_an_ownable_root_is_accounted_for():
    sites = _bulk_create_sites_of_ownable_roots()

    assert sorted(sites - BULK_CREATE_SITES.keys()) == [], "a new bulk_create of an ownable root: make it send rows_bulk_created and list it"
    assert sorted(BULK_CREATE_SITES.keys() - sites) == [], "a listed bulk_create site no longer exists"
