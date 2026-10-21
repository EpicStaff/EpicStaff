"""Which rows a plugin's service account owns, and the guards that keep every write path covered."""

import ast
from pathlib import Path

import pytest
from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.db import connection, models, transaction
from django.db.models.signals import post_delete, pre_delete
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
from tables.models.llm_models import LLMModel
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
# Each `bulk_create` (or the `_insert` it is built on) of an ownable root outside tests, by file
# and function, and how its rows get owned (or why they never need to be).
BULK_CREATE_SITES = {
    "tables/services/storage_service/db_sync.py::StorageFileSync.on_bulk_upload": "sends rows_bulk_created for the files it inserts; its folder insert makes folders only, which are never owned",
    "tables/services/storage_service/db_sync.py::_insert_skipping_live_paths": "inserts the uploaded files; its caller StorageFileSync.on_bulk_upload sends rows_bulk_created for the ids it returns",
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


def test_deleting_a_root_leaves_its_ownership_row_as_a_tombstone(owner, acme):
    graph = Graph.objects.get(pk=owner.post("/api/graphs/", {"name": "Short-lived"}, format="json").json()["id"])

    graph.delete()
    Graph.all_objects.get(pk=graph.pk).purge()

    assert _owned(Graph, graph.pk) is not None


def test_deleting_the_organization_takes_its_ownership_rows(owner, acme):
    owner.post("/api/graphs/", {"name": "Goes with the org"}, format="json")

    Organization.objects.filter(pk=acme.pk).delete()

    assert not PluginOwnedResource.objects.exists()


def test_a_row_outside_the_service_account_s_organization_is_never_owned(
    weather_backend, service_account_key, acme, beta, log_messages
):
    plugin = weather_backend(access=OWNER_ACCESS)
    _authenticate_directly(service_account_key(plugin, acme))

    foreign = Graph.objects.create(name="Beta's", org=beta)
    built_in = LLMModel.objects.create(name="shared-model", org=None)
    own = Graph.objects.create(name="Acme's", org=acme)

    assert (_owned(Graph, foreign.pk), _owned(LLMModel, built_in.pk)) == (None, None)
    assert _owned(Graph, own.pk) is not None
    assert [line for line in log_messages if line.startswith("plugins.ownership.foreign_row")] == [
        f"plugins.ownership.foreign_row plugin=weather model=tables.Graph pk={foreign.pk}",
        f"plugins.ownership.foreign_row plugin=weather model=tables.LLMModel pk={built_in.pk}",
    ]


def test_a_created_root_is_named_by_its_name_or_else_its_custom_name(weather_backend, service_account_key, acme):
    plugin = weather_backend(access=OWNER_ACCESS)
    _authenticate_directly(service_account_key(plugin, acme))

    Graph.objects.create(name="Forecast", org=acme)
    LLMConfig.objects.create(custom_name="Weather summaries", org=acme)

    assert [root.label for root in request_scope.current_scope().created] == ["Forecast", "Weather summaries"]


def test_a_large_bulk_upload_is_owned_in_batches(weather_backend, service_account_key, acme):
    plugin = weather_backend(access=OWNER_ACCESS)
    principal = _authenticate_directly(service_account_key(plugin, acme))
    paths = [(f"many/{index}.txt", 1) for index in range(1500)]

    with CaptureQueriesContext(connection) as captured:
        StorageFileSync.on_bulk_upload(acme.pk, paths, user=principal)

    ownership_inserts = [query for query in captured.captured_queries if query["sql"].startswith('INSERT INTO "plugins_pluginownedresource"')]
    assert len(ownership_inserts) == 2
    assert PluginOwnedResource.objects.filter(org=acme).count() == 1500


def _authenticate_directly(raw_key):
    """Authenticate as the view would, without the middleware: the scope stays open for the test."""
    request = Request(
        APIRequestFactory().post("/", HTTP_AUTHORIZATION=f"PluginKey {raw_key}", HTTP_X_PLUGIN_NETWORK_SECRET=GATEWAY_SECRET),
        authenticators=[PluginServiceAccountAuthentication()],
    )
    return request.user


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


def test_the_plugins_app_listens_to_no_delete_of_an_ownable_root():
    # Any delete listener on a model turns off Django's column deferral for every row of it
    # a cascade deletes; an organization delete would then load every flow in full. Other
    # apps' own listeners (a Python tool's, a secret's) are theirs to keep.
    listening = sorted(
        f"{model._meta.label}: {signal_name} {receiver.__module__}.{receiver.__qualname__}"
        for model in ownable_models()
        for signal_name, signal in (("pre_delete", pre_delete), ("post_delete", post_delete))
        for receivers in signal._live_receivers(model)
        for receiver in receivers
        if receiver.__module__.split(".")[0] == "plugins"
    )

    assert listening == []


def test_every_ownable_root_belongs_to_an_organization():
    # The recorder owns a row only when its `org` is the service account's organization.
    assert sorted(
        model._meta.label
        for model in ownable_models()
        if getattr(model._meta.get_field("org"), "related_model", None) is not Organization
    ) == []


def test_every_ownable_root_has_an_integer_key():
    assert all(
        isinstance(model._meta.pk, (models.AutoField, models.BigAutoField, models.IntegerField))
        for model in ownable_models()
    )
    assert {apps.get_model(label) for label in EXTRA_OWNABLE_MODELS} <= set(ownable_models())


# `_insert` sends no `post_save` either, so a call of it escapes the recorder just as
# `bulk_create` does.
BULK_INSERT_METHODS = frozenset({"bulk_create", "_insert"})


class _BulkCreateFinder(ast.NodeVisitor):
    """`<Model>.<manager>.bulk_create(` and `._insert(` calls, by enclosing function (`Class.method`)."""

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
            and function.attr in BULK_INSERT_METHODS
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
