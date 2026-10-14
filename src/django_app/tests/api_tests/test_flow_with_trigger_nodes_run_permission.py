"""Copying, importing or restoring a flow that holds trigger nodes needs flows:RUN.

Copy, import (including replace_existing), partial import, create-graph from a
version and version restore refuse a caller without RUN with 403
`flow_with_trigger_nodes_requires_run_permission` and write nothing, when the
source (the flow, the file, the snapshot) holds a webhook, Telegram or schedule
trigger node. Without trigger nodes, or with RUN, they work as before. Another
org's flow or version is still a 404.
"""

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from rbac.models import OrganizationUser, Role, RolePermission
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
from tests.helpers import data_to_json_file
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

DENIED = {
    "status_code": 403,
    "code": "flow_with_trigger_nodes_requires_run_permission",
    "message": (
        "This flow contains trigger nodes (webhook, Telegram, schedule). Copying, "
        "importing or restoring it requires the Run permission on flows."
    ),
}
FLOWS_EDITOR = Permission.CREATE | Permission.READ | Permission.UPDATE
TRIGGER_MODELS = (WebhookTriggerNode, TelegramTriggerNode, ScheduleTriggerNode)


@pytest.fixture(autouse=True)
def _no_telegram_calls(mock_telegram_service):
    """Telegram node saves register the bot with Telegram; never under test here."""


def _member(django_user_model, org, flows_permissions, name):
    """A member whose custom role holds `flows_permissions` on flows and webhooks, and
    create/read on tools (for the tool import endpoint)."""
    role = Role.objects.create(name=name, org=org, is_built_in=False)
    for resource_type in (ResourceType.FLOWS, ResourceType.WEBHOOKS):
        RolePermission.objects.create(
            role=role, resource_type=resource_type, permissions=int(flows_permissions)
        )
    RolePermission.objects.create(
        role=role,
        resource_type=ResourceType.TOOLS,
        permissions=int(Permission.CREATE | Permission.READ),
    )
    user = django_user_model.objects.create_user(
        email=f"{name}@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org, role=role)
    return user


def _client(client_as, django_user_model, org, flows_permissions, name):
    client = client_as(_member(django_user_model, org, flows_permissions, name))
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.fixture
def editor_client(client_as, django_user_model, acme):
    return _client(client_as, django_user_model, acme, FLOWS_EDITOR, "strict-editor")


@pytest.fixture
def runner_client(client_as, django_user_model, acme):
    return _client(
        client_as, django_user_model, acme, FLOWS_EDITOR | Permission.RUN, "strict-runner"
    )


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


def _flow_with_triggers(org, name="Flow with triggers"):
    graph = _plain_flow(org, name)
    WebhookTriggerNode.objects.create(
        graph=graph,
        node_name="Incoming",
        webhook_trigger=WebhookTrigger.objects.create(
            path=f"{name}-path".replace(" ", "-"), org=org
        ),
        python_code=PythonCode.objects.create(code="def main(**kwargs): ..."),
    )
    TelegramTriggerNode.objects.create(graph=graph, node_name="Bot")
    ScheduleTriggerNode.objects.create(graph=graph, node_name="Hourly")
    return graph


def _row_counts():
    return {
        "graphs": Graph.objects.count(),
        "python_nodes": PythonNode.objects.count(),
        "webhook_triggers": WebhookTrigger.objects.count(),
        **{model.__name__: model.objects.count() for model in TRIGGER_MODELS},
    }


def _trigger_count(graph):
    return sum(model.objects.filter(graph=graph).count() for model in TRIGGER_MODELS)


# ── POST /api/graphs/<id>/copy/ ──────────────────────────────────────────────


def _copy(client, graph):
    return client.post(reverse("graphs-copy", args=[graph.id]), {}, format="json")


@pytest.mark.django_db
class TestCopy:
    def test_without_run_is_403_and_writes_nothing(self, editor_client, acme):
        source = _flow_with_triggers(acme)
        before = _row_counts()

        response = _copy(editor_client, source)

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        assert response.data == DENIED
        assert _row_counts() == before

    @pytest.mark.parametrize("trigger_model", TRIGGER_MODELS)
    def test_a_single_trigger_of_any_type_is_enough(self, editor_client, acme, trigger_model):
        source = _plain_flow(acme)
        if trigger_model is WebhookTriggerNode:
            trigger_model.objects.create(
                graph=source, node_name="w", python_code=PythonCode.objects.create(code="x")
            )
        else:
            trigger_model.objects.create(graph=source, node_name="t")

        response = _copy(editor_client, source)

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        assert response.data["code"] == DENIED["code"]

    def test_flow_without_triggers_copies_without_run(self, editor_client, acme):
        response = _copy(editor_client, _plain_flow(acme))

        assert response.status_code == status.HTTP_201_CREATED, response.content

    def test_with_run_copies_the_triggers(self, runner_client, acme):
        response = _copy(runner_client, _flow_with_triggers(acme))

        assert response.status_code == status.HTTP_201_CREATED, response.content
        assert _trigger_count(Graph.objects.get(pk=response.data["id"])) == 3

    def test_superadmin_needs_no_role(self, client_as, superadmin, acme):
        client = client_as(superadmin)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

        response = _copy(client, _flow_with_triggers(acme))

        assert response.status_code == status.HTTP_201_CREATED, response.content

    def test_foreign_flow_is_404(self, editor_client, beta):
        response = _copy(editor_client, _flow_with_triggers(beta, name="Beta flow"))

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


# ── POST /api/graphs/import/ ─────────────────────────────────────────────────


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


@pytest.mark.django_db
class TestImport:
    def test_without_run_is_403_and_writes_nothing(self, editor_client, acme):
        export_data = _export(_flow_with_triggers(acme))
        before = _row_counts()

        response = _import(editor_client, export_data)

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        assert response.data == DENIED
        assert _row_counts() == before

    def test_a_trigger_in_a_subflow_is_enough(self, editor_client, acme):
        child = _flow_with_triggers(acme, name="Child flow")
        parent = _plain_flow(acme, name="Parent flow")
        SubGraphNode.objects.create(graph=parent, node_name="child", subgraph=child)
        export_data = _export(parent)
        before = _row_counts()

        response = _import(editor_client, export_data)

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        assert _row_counts() == before

    def test_replace_existing_without_run_is_403_and_keeps_the_flow(self, editor_client, acme):
        flow = _flow_with_triggers(acme)
        export_data = _export(flow)
        flow.refresh_from_db()
        save_version_before = flow.save_version
        before = _row_counts()

        response = _import(editor_client, export_data, preserve_uuids=True, replace_existing=True)

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        assert _row_counts() == before
        assert not GraphVersion.objects.filter(graph=flow).exists()
        flow.refresh_from_db()
        assert flow.save_version == save_version_before

    def test_flow_without_triggers_imports_without_run(self, editor_client, acme):
        response = _import(editor_client, _export(_plain_flow(acme)))

        assert response.status_code == status.HTTP_200_OK, response.content

    def test_with_run_imports_the_triggers(self, runner_client, acme):
        export_data = _export(_flow_with_triggers(acme))
        before = _row_counts()

        response = _import(runner_client, export_data)

        assert response.status_code == status.HTTP_200_OK, response.content
        assert _row_counts()["ScheduleTriggerNode"] == before["ScheduleTriggerNode"] + 1


# ── POST /api/graphs/<id>/partial-import/ ────────────────────────────────────


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


@pytest.mark.django_db
class TestPartialImport:
    def test_importing_a_trigger_without_run_is_403_and_writes_nothing(self, editor_client, acme):
        source = _flow_with_triggers(acme)
        target = _plain_flow(acme, name="Target")
        export_data = _partial_export(
            source,
            NodeRef(entity_type=EntityType.PYTHON_NODE, node_id=source.python_node_list.get().id),
            NodeRef(
                entity_type=EntityType.SCHEDULE_TRIGGER_NODE,
                node_id=source.schedule_trigger_node_list.get().id,
            ),
        )
        before = _row_counts()

        response = _partial_import(editor_client, target, export_data)

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        assert response.data == DENIED
        assert _row_counts() == before

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

    def test_with_run_imports_the_trigger(self, runner_client, acme):
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


# ── /api/graph-versions/<id>/create-graph/ and /restore/ ─────────────────────


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


@pytest.mark.django_db
class TestCreateGraphFromVersion:
    def test_without_run_is_403_and_writes_nothing(self, editor_client, acme):
        version = _version_of(_flow_with_triggers(acme))
        before = _row_counts()

        response = _create_graph(editor_client, version)

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        assert response.data == DENIED
        assert _row_counts() == before

    def test_snapshot_without_triggers_works_without_run(self, editor_client, acme):
        response = _create_graph(editor_client, _version_of(_plain_flow(acme)))

        assert response.status_code == status.HTTP_201_CREATED, response.content

    def test_with_run_recreates_the_triggers(self, runner_client, acme):
        response = _create_graph(runner_client, _version_of(_flow_with_triggers(acme)))

        assert response.status_code == status.HTTP_201_CREATED, response.content
        assert _trigger_count(Graph.objects.get(pk=response.data["graph_id"])) == 3

    def test_foreign_version_is_404(self, editor_client, beta):
        version = _version_of(_flow_with_triggers(beta, name="Beta flow"))

        response = _create_graph(editor_client, version)

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
class TestRestore:
    def test_without_run_is_403_and_writes_nothing(self, editor_client, acme):
        flow = _flow_with_triggers(acme)
        version = _version_of(flow)
        flow.refresh_from_db()
        save_version_before = flow.save_version
        before = _row_counts()
        versions_before = GraphVersion.objects.filter(graph=flow).count()

        response = _restore(editor_client, version, query="?backup=true")

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        assert response.data == DENIED
        assert _row_counts() == before
        assert GraphVersion.objects.filter(graph=flow).count() == versions_before
        flow.refresh_from_db()
        assert flow.save_version == save_version_before

    def test_snapshot_without_triggers_restores_without_run_over_a_flow_with_triggers(
        self, editor_client, acme
    ):
        flow = _plain_flow(acme)
        version = _version_of(flow)
        ScheduleTriggerNode.objects.create(graph=flow, node_name="Added later")

        response = _restore(editor_client, version)

        assert response.status_code == status.HTTP_200_OK, response.content
        assert _trigger_count(flow) == 0

    def test_with_run_restores_the_triggers(self, runner_client, acme):
        flow = _flow_with_triggers(acme)
        version = _version_of(flow)

        response = _restore(runner_client, version)

        assert response.status_code == status.HTTP_200_OK, response.content
        assert _trigger_count(flow) == 3

    def test_foreign_version_is_404(self, editor_client, beta):
        version = _version_of(_flow_with_triggers(beta, name="Beta flow"))

        response = _restore(editor_client, version)

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


# ── loose nodes only: a partial import never imports Flow entries ────────────


@pytest.mark.django_db
def test_partial_import_ignores_a_flow_entry_it_does_not_import(editor_client, acme):
    """A crafted partial file: a loose Python node plus a `Flow` entry holding a
    schedule node. Partial import creates only the loose node, so no RUN is needed."""
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


# ── a flow smuggled into another entity's import file ────────────────────────


def _tool_import(client, export_data):
    return client.post(
        "/api/python-code-tool/import/",
        {"file": data_to_json_file(data=export_data, filename="tools.json")},
        format="multipart",
    )


@pytest.mark.django_db
class TestFlowInAToolImportFile:
    def _tool_file_carrying_a_flow(self, acme):
        export_data = _export(_flow_with_triggers(acme, name="Smuggled"))
        export_data["main_entity"] = EntityType.PYTHON_CODE_TOOL
        return export_data

    def test_without_run_is_403_and_writes_nothing(self, editor_client, acme):
        export_data = self._tool_file_carrying_a_flow(acme)
        before = _row_counts()

        response = _tool_import(editor_client, export_data)

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        assert response.data == DENIED
        assert _row_counts() == before

    def test_with_run_imports_it(self, runner_client, acme):
        export_data = self._tool_file_carrying_a_flow(acme)
        before = _row_counts()

        response = _tool_import(runner_client, export_data)

        assert response.status_code == status.HTTP_200_OK, response.content
        assert _row_counts()["graphs"] == before["graphs"] + 1


# ── user API keys act with their owner's role ────────────────────────────────


def _api_key_client(issue_api_key, user, org):
    raw_key, _ = issue_api_key(user=user)
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_key, HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.fixture
def editor_key_client(django_user_model, issue_api_key, acme):
    return _api_key_client(
        issue_api_key, _member(django_user_model, acme, FLOWS_EDITOR, "key-editor"), acme
    )


@pytest.fixture
def runner_key_client(django_user_model, issue_api_key, acme):
    user = _member(django_user_model, acme, FLOWS_EDITOR | Permission.RUN, "key-runner")
    return _api_key_client(issue_api_key, user, acme)


@pytest.mark.django_db
class TestUserApiKey:
    def test_copy(self, editor_key_client, runner_key_client, acme):
        source = _flow_with_triggers(acme)
        before = _row_counts()

        denied = _copy(editor_key_client, source)
        assert denied.status_code == status.HTTP_403_FORBIDDEN, denied.content
        assert denied.data == DENIED
        assert _row_counts() == before

        allowed = _copy(runner_key_client, source)
        assert allowed.status_code == status.HTTP_201_CREATED, allowed.content

    def test_import(self, editor_key_client, runner_key_client, acme):
        export_data = _export(_flow_with_triggers(acme))
        before = _row_counts()

        denied = _import(editor_key_client, export_data)
        assert denied.status_code == status.HTTP_403_FORBIDDEN, denied.content
        assert denied.data == DENIED
        assert _row_counts() == before

        allowed = _import(runner_key_client, export_data)
        assert allowed.status_code == status.HTTP_200_OK, allowed.content

    def test_restore(self, editor_key_client, runner_key_client, acme):
        flow = _flow_with_triggers(acme)
        version = _version_of(flow)
        before = _row_counts()

        denied = _restore(editor_key_client, version)
        assert denied.status_code == status.HTTP_403_FORBIDDEN, denied.content
        assert denied.data == DENIED
        assert _row_counts() == before

        allowed = _restore(runner_key_client, version)
        assert allowed.status_code == status.HTTP_200_OK, allowed.content
        assert _trigger_count(flow) == 3
