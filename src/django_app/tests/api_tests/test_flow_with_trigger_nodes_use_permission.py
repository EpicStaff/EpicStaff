"""Copying, importing or restoring a flow that holds trigger nodes needs flows:USE.

Copy, import (including replace_existing), partial import, create-graph from a
version and version restore refuse a caller without USE with 403
`flow_with_trigger_nodes_requires_use_permission` and write nothing, when the
source (the flow, the file, the snapshot) holds a webhook, Telegram or schedule
trigger node. Without trigger nodes, or with USE, they work as before. Another
org's flow or version is still a 404.
"""

import pytest
from django.urls import reverse
from rest_framework import status

from rbac.models.enums import Permission, ResourceType
from tables.graph_versioning.services import GraphVersioningService
from tables.import_export.enums import EntityType
from tables.import_export.registry import entity_registry
from tables.import_export.services.export_service import ExportService
from tables.import_export.services.partial_export_service import (
    GraphPartialExportService,
    NodeRef,
)
from tables.models import Graph, GraphVersion, PythonCode, StartNode, WebhookTrigger
from tables.models.graph_models import (
    Edge,
    PythonNode,
    ScheduleTriggerNode,
    SubGraphNode,
    TelegramTriggerNode,
    WebhookTriggerNode,
)
from tests.custom_role_fixtures import *  # noqa: F401,F403
from tests.helpers import data_to_json_file
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

DENIED_CODE = "flow_with_trigger_nodes_requires_use_permission"
FLOWS_EDITOR = Permission.CREATE | Permission.READ | Permission.UPDATE
TRIGGER_MODELS = (WebhookTriggerNode, TelegramTriggerNode, ScheduleTriggerNode)


@pytest.fixture(autouse=True)
def _no_telegram_calls(mock_telegram_service):
    """Telegram node saves register the bot with Telegram; never under test here."""


def _grants(flows_permissions):
    """`flows_permissions` on flows and webhooks, plus what the tool, MCP and
    audit-preset import endpoints need of their own."""
    return {
        ResourceType.FLOWS: flows_permissions,
        ResourceType.WEBHOOKS: flows_permissions,
        ResourceType.TOOLS: Permission.CREATE | Permission.READ,
        ResourceType.AUDIT: Permission.READ,
    }


@pytest.fixture
def editor_client(custom_role_client, acme):
    return custom_role_client(acme, _grants(FLOWS_EDITOR), "strict-editor")


@pytest.fixture
def runner_client(custom_role_client, acme):
    return custom_role_client(acme, _grants(FLOWS_EDITOR | Permission.USE), "strict-runner")


def _plain_flow(org, name="Plain flow"):
    graph = Graph.objects.create(name=name, org=org)
    start = StartNode.objects.create(graph=graph, variables={})
    work = PythonNode.objects.create(
        graph=graph,
        node_name="work",
        python_code=PythonCode.objects.create(code="def main(**kwargs):\n    return None\n"),
    )
    Edge.objects.create(graph=graph, start_node_id=start.id, end_node_id=work.id)
    return graph


def _add_webhook_trigger_node(graph):
    return WebhookTriggerNode.objects.create(
        graph=graph,
        node_name="Incoming",
        webhook_trigger=WebhookTrigger.objects.create(
            path=f"{graph.name}-path".replace(" ", "-"), org=graph.org
        ),
        python_code=PythonCode.objects.create(code="def main(**kwargs): ..."),
    )


def _add_telegram_trigger_node(graph):
    return TelegramTriggerNode.objects.create(graph=graph, node_name="Bot")


def _add_schedule_trigger_node(graph):
    return ScheduleTriggerNode.objects.create(graph=graph, node_name="Hourly")


ADD_TRIGGER_NODE = [
    pytest.param(_add_webhook_trigger_node, id="webhook"),
    pytest.param(_add_telegram_trigger_node, id="telegram"),
    pytest.param(_add_schedule_trigger_node, id="schedule"),
]


def _flow_with_triggers(org, name="Flow with triggers"):
    graph = _plain_flow(org, name)
    _add_webhook_trigger_node(graph)
    _add_telegram_trigger_node(graph)
    _add_schedule_trigger_node(graph)
    return graph


def _row_counts():
    return {
        "graphs": Graph.objects.count(),
        "graph_versions": GraphVersion.objects.count(),
        "python_nodes": PythonNode.objects.count(),
        "webhook_triggers": WebhookTrigger.objects.count(),
        **{model.__name__: model.objects.count() for model in TRIGGER_MODELS},
    }


def _trigger_count(graph):
    return sum(model.objects.filter(graph=graph).count() for model in TRIGGER_MODELS)


def _assert_refused(response):
    assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
    assert response.data["code"] == DENIED_CODE


# ── requests ─────────────────────────────────────────────────────────────────


def _copy(client, graph):
    return client.post(reverse("graphs-copy", args=[graph.id]), {}, format="json")


def _export(graph):
    return ExportService(entity_registry).export_entities(
        EntityType.GRAPH, [graph.id], org_id=graph.org_id
    )


def _import(client, export_data, **options):
    return client.post(
        reverse("graphs-import-entity"),
        {"file": data_to_json_file(data=export_data, filename="flow.json"), **options},
        format="multipart",
    )


def _partial_export(source, *node_refs):
    result = GraphPartialExportService(entity_registry).export(
        list(node_refs), org_id=source.org_id
    )
    assert not result.has_errors, result.errors
    return result.data


def _partial_import(client, graph, export_data):
    return client.post(
        reverse("graphs-partial-import", args=[graph.id]),
        {"file": data_to_json_file(data=export_data, filename="nodes.json")},
        format="multipart",
    )


def _version_of(graph):
    return GraphVersioningService().save_version(graph=graph, name="v1")


def _create_graph(client, version):
    return client.post(reverse("graph-versions-create-graph", args=[version.id]), format="json")


def _restore(client, version, query=""):
    version.graph.refresh_from_db()
    return client.post(
        reverse("graph-versions-restore", args=[version.id]) + query,
        {"save_version": version.graph.save_version},
        format="json",
    )


# ── every operation that recreates trigger nodes, for every kind of caller ───
#
# Each `_prepare_*` builds, in `org`, a source that holds trigger nodes and
# returns the request that recreates them; `success` is its status with USE.


def _prepare_copy(org):
    source = _flow_with_triggers(org)
    return lambda client: _copy(client, source)


def _prepare_import(org):
    export_data = _export(_flow_with_triggers(org))
    return lambda client: _import(client, export_data)


def _prepare_partial_import(org):
    source = _flow_with_triggers(org)
    target = _plain_flow(org, name="Target")
    export_data = _partial_export(
        source,
        NodeRef(entity_type=EntityType.PYTHON_NODE, node_id=source.python_node_list.get().id),
        NodeRef(
            entity_type=EntityType.SCHEDULE_TRIGGER_NODE,
            node_id=source.schedule_trigger_node_list.get().id,
        ),
    )
    return lambda client: _partial_import(client, target, export_data)


def _prepare_create_graph(org):
    version = _version_of(_flow_with_triggers(org))
    return lambda client: _create_graph(client, version)


def _prepare_restore(org):
    version = _version_of(_flow_with_triggers(org))
    return lambda client: _restore(client, version)


OPERATIONS = [
    pytest.param(_prepare_copy, status.HTTP_201_CREATED, id="copy"),
    pytest.param(_prepare_import, status.HTTP_200_OK, id="import"),
    pytest.param(_prepare_partial_import, status.HTTP_200_OK, id="partial-import"),
    pytest.param(_prepare_create_graph, status.HTTP_201_CREATED, id="create-graph"),
    pytest.param(_prepare_restore, status.HTTP_200_OK, id="restore"),
]
# Operations on an existing flow or version, which another org's caller must not see.
OPERATIONS_ON_A_STORED_SOURCE = [
    param for param in OPERATIONS if param.id in {"copy", "partial-import", "create-graph", "restore"}
]
AUTHENTICATION = [
    pytest.param(False, id="session"),
    pytest.param(True, id="user-api-key"),
]


@pytest.mark.django_db
@pytest.mark.parametrize("via_api_key", AUTHENTICATION)
@pytest.mark.parametrize(("prepare", "success"), OPERATIONS)
def test_without_use_is_refused_and_writes_nothing(
    custom_role_client, acme, prepare, success, via_api_key
):
    client = custom_role_client(acme, _grants(FLOWS_EDITOR), "no-use", via_api_key=via_api_key)
    send = prepare(acme)
    before = _row_counts()

    response = send(client)

    _assert_refused(response)
    assert _row_counts() == before


@pytest.mark.django_db
@pytest.mark.parametrize("via_api_key", AUTHENTICATION)
@pytest.mark.parametrize(("prepare", "success"), OPERATIONS)
def test_with_use_succeeds(custom_role_client, acme, prepare, success, via_api_key):
    client = custom_role_client(
        acme, _grants(FLOWS_EDITOR | Permission.USE), "runner", via_api_key=via_api_key
    )
    send = prepare(acme)

    response = send(client)

    assert response.status_code == success, response.content


@pytest.mark.django_db
@pytest.mark.parametrize(("prepare", "success"), OPERATIONS)
def test_superadmin_needs_no_role(org_client_as, superadmin, acme, prepare, success):
    send = prepare(acme)

    response = send(org_client_as(superadmin, acme))

    assert response.status_code == success, response.content


@pytest.mark.django_db
@pytest.mark.parametrize(("prepare", "success"), OPERATIONS_ON_A_STORED_SOURCE)
def test_another_orgs_source_is_404_not_the_use_403(editor_client, beta, prepare, success):
    send = prepare(beta)
    before = _row_counts()

    response = send(editor_client)

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content
    assert _row_counts() == before


# ── POST /api/graphs/<id>/copy/ ──────────────────────────────────────────────


@pytest.mark.django_db
class TestCopy:
    @pytest.mark.parametrize("add_trigger_node", ADD_TRIGGER_NODE)
    def test_a_single_trigger_of_any_type_is_enough(self, editor_client, acme, add_trigger_node):
        source = _plain_flow(acme)
        add_trigger_node(source)
        before = _row_counts()

        response = _copy(editor_client, source)

        _assert_refused(response)
        assert _row_counts() == before

    def test_flow_without_triggers_copies_without_use(self, editor_client, acme):
        response = _copy(editor_client, _plain_flow(acme))

        assert response.status_code == status.HTTP_201_CREATED, response.content

    def test_with_use_copies_the_triggers(self, runner_client, acme):
        response = _copy(runner_client, _flow_with_triggers(acme))

        assert response.status_code == status.HTTP_201_CREATED, response.content
        assert _trigger_count(Graph.objects.get(pk=response.data["id"])) == 3


# ── POST /api/graphs/import/ ─────────────────────────────────────────────────


@pytest.mark.django_db
class TestImport:
    def test_a_trigger_in_a_subflow_is_enough(self, editor_client, acme):
        child = _flow_with_triggers(acme, name="Child flow")
        parent = _plain_flow(acme, name="Parent flow")
        SubGraphNode.objects.create(graph=parent, node_name="child", subgraph=child)
        export_data = _export(parent)
        before = _row_counts()

        response = _import(editor_client, export_data)

        _assert_refused(response)
        assert _row_counts() == before

    def test_replace_existing_without_use_is_403_and_keeps_the_flow(self, editor_client, acme):
        flow = _flow_with_triggers(acme)
        export_data = _export(flow)
        flow.refresh_from_db()
        save_version_before = flow.save_version
        before = _row_counts()

        response = _import(editor_client, export_data, preserve_uuids=True, replace_existing=True)

        _assert_refused(response)
        assert _row_counts() == before
        flow.refresh_from_db()
        assert flow.save_version == save_version_before

    def test_flow_without_triggers_imports_without_use(self, editor_client, acme):
        response = _import(editor_client, _export(_plain_flow(acme)))

        assert response.status_code == status.HTTP_200_OK, response.content

    def test_with_use_imports_the_triggers(self, runner_client, acme):
        export_data = _export(_flow_with_triggers(acme))
        before = _row_counts()

        response = _import(runner_client, export_data)

        assert response.status_code == status.HTTP_200_OK, response.content
        after = _row_counts()
        assert {model.__name__: after[model.__name__] for model in TRIGGER_MODELS} == {
            model.__name__: before[model.__name__] + 1 for model in TRIGGER_MODELS
        }


# ── POST /api/graphs/<id>/partial-import/ ────────────────────────────────────


@pytest.mark.django_db
class TestPartialImport:
    def test_target_triggers_do_not_matter(self, editor_client, acme):
        source = _plain_flow(acme, name="Source")
        target = _flow_with_triggers(acme, name="Target with triggers")
        export_data = _partial_export(
            source,
            NodeRef(entity_type=EntityType.PYTHON_NODE, node_id=source.python_node_list.get().id),
        )

        response = _partial_import(editor_client, target, export_data)

        assert response.status_code == status.HTTP_200_OK, response.content
        assert target.python_node_list.count() == 2

    def test_with_use_imports_the_trigger(self, runner_client, acme):
        source = _flow_with_triggers(acme)
        target = _plain_flow(acme, name="Target")
        export_data = _partial_export(
            source,
            NodeRef(
                entity_type=EntityType.WEBHOOK_TRIGGER_NODE,
                node_id=source.webhook_trigger_node_list.get().id,
            ),
        )

        response = _partial_import(runner_client, target, export_data)

        assert response.status_code == status.HTTP_200_OK, response.content
        assert target.webhook_trigger_node_list.count() == 1

    def test_a_flow_entry_it_does_not_import_does_not_matter(self, editor_client, acme):
        """A crafted partial file: a loose Python node plus a `Flow` entry holding
        trigger nodes. Partial import creates only the loose node, so no USE is needed."""
        source = _plain_flow(acme, name="Source")
        target = _plain_flow(acme, name="Target")
        export_data = _partial_export(
            source,
            NodeRef(entity_type=EntityType.PYTHON_NODE, node_id=source.python_node_list.get().id),
        )
        export_data[EntityType.GRAPH] = _export(_flow_with_triggers(acme))[EntityType.GRAPH]
        before = _row_counts()

        response = _partial_import(editor_client, target, export_data)

        assert response.status_code == status.HTTP_200_OK, response.content
        assert target.python_node_list.count() == 2
        after = _row_counts()
        assert after["graphs"] == before["graphs"]
        assert all(after[model.__name__] == before[model.__name__] for model in TRIGGER_MODELS)


# ── /api/graph-versions/<id>/create-graph/ and /restore/ ─────────────────────


@pytest.mark.django_db
class TestCreateGraphFromVersion:
    def test_snapshot_without_triggers_works_without_use(self, editor_client, acme):
        response = _create_graph(editor_client, _version_of(_plain_flow(acme)))

        assert response.status_code == status.HTTP_201_CREATED, response.content

    def test_with_use_recreates_the_triggers(self, runner_client, acme):
        response = _create_graph(runner_client, _version_of(_flow_with_triggers(acme)))

        assert response.status_code == status.HTTP_201_CREATED, response.content
        assert _trigger_count(Graph.objects.get(pk=response.data["graph_id"])) == 3


@pytest.mark.django_db
class TestRestore:
    def test_with_backup_without_use_is_403_and_writes_nothing(self, editor_client, acme):
        flow = _flow_with_triggers(acme)
        version = _version_of(flow)
        flow.refresh_from_db()
        save_version_before = flow.save_version
        before = _row_counts()

        response = _restore(editor_client, version, query="?backup=true")

        _assert_refused(response)
        assert _row_counts() == before
        flow.refresh_from_db()
        assert flow.save_version == save_version_before

    def test_snapshot_without_triggers_restores_without_use_over_a_flow_with_triggers(
        self, editor_client, acme
    ):
        flow = _plain_flow(acme)
        version = _version_of(flow)
        ScheduleTriggerNode.objects.create(graph=flow, node_name="Added later")

        response = _restore(editor_client, version)

        assert response.status_code == status.HTTP_200_OK, response.content
        assert _trigger_count(flow) == 0

    def test_with_use_restores_the_triggers(self, runner_client, acme):
        flow = _flow_with_triggers(acme)
        version = _version_of(flow)

        response = _restore(runner_client, version)

        assert response.status_code == status.HTTP_200_OK, response.content
        assert _trigger_count(flow) == 3


# ── a flow smuggled into another entity's import file ────────────────────────

OTHER_ENTITY_IMPORTS = [
    pytest.param("/api/python-code-tool/import/", EntityType.PYTHON_CODE_TOOL, id="python-tool"),
    pytest.param("/api/mcp-tools/import/", EntityType.MCP_TOOL, id="mcp-tool"),
    pytest.param(
        "/api/audit-filter-presets/import/", EntityType.AUDIT_FILTER_PRESET, id="audit-preset"
    ),
]


def _file_carrying_a_flow(acme, main_entity):
    export_data = _export(_flow_with_triggers(acme, name="Smuggled"))
    export_data["main_entity"] = main_entity
    return export_data


def _post_import_file(client, url, export_data):
    return client.post(
        url,
        {"file": data_to_json_file(data=export_data, filename="entities.json")},
        format="multipart",
    )


@pytest.mark.django_db
@pytest.mark.parametrize(("url", "main_entity"), OTHER_ENTITY_IMPORTS)
class TestFlowInAnotherEntitysImportFile:
    def test_without_use_is_403_and_writes_nothing(self, editor_client, acme, url, main_entity):
        export_data = _file_carrying_a_flow(acme, main_entity)
        before = _row_counts()

        response = _post_import_file(editor_client, url, export_data)

        _assert_refused(response)
        assert _row_counts() == before

    def test_with_use_imports_it(self, runner_client, acme, url, main_entity):
        export_data = _file_carrying_a_flow(acme, main_entity)
        before = _row_counts()

        response = _post_import_file(runner_client, url, export_data)

        assert response.status_code == status.HTTP_200_OK, response.content
        assert _row_counts()["graphs"] == before["graphs"] + 1
