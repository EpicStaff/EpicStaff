"""Recycle-bin endpoints: list, restore and purge. Scoped to the active org.
READ lists, CREATE restores, DELETE purges."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

import pytest
from django.apps import apps
from django.core.exceptions import FieldDoesNotExist
from django.db import connection
from django.db.models import Model
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from agents.models import AgentDefinition, Surface
from agents.views.agent_definition_views import AgentDefinitionViewSet
from agents.views.surface_views import SurfaceViewSet
from rbac.models import Organization, OrganizationUser, Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from tables.models import (
    AgentNode,
    CrewNode,
    Graph,
    PythonCode,
    PythonCodeTool,
    PythonNode,
    SourceCollection,
    StartNode,
    TaskNode,
)
from tables.models.graph_models import TelegramTriggerNode
from tables.models.mcp_models import McpTool
from tables.services.recycle_bin.flow_bin_service import FLOW_BIN_NODE_TYPES
from tables.services.recycle_bin.registry import bin_resources
from tables.views.knowledge_views.collection_management_views import SourceCollectionViewSet
from tables.views.model_view_sets import GraphViewSet, McpToolViewSet, PythonCodeToolViewSet
from tables.views.recycle_bin_mixins import RECYCLE_BIN_ACTION_MAP, RecycleBinActionsMixin
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

FLOWS_URL = "/api/graphs/"
PYTHON_TOOLS_URL = "/api/python-code-tool/"
AGENTS_URL = "/api/agent-definitions/"
SURFACES_URL = "/api/surfaces/"
SETTINGS_URL = "/api/recycle-bin/settings/"


@pytest.fixture(autouse=True)
def retention_seven_days(settings):
    # A developer's local .env can set DJANGO_RECYCLE_BIN_RETENTION_DAYS.
    settings.RECYCLE_BIN_RETENTION_DAYS = 7


@pytest.fixture
def admin_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.fixture
def client_with_role(client_as, django_user_model, acme):
    """Factory: a client in Acme whose custom role holds `bits` on one resource type."""

    def _make(resource_type: ResourceType, bits: Permission) -> APIClient:
        label = f"{resource_type.value}-{int(bits)}"
        role = Role.objects.create(name=f"Bin test {label}", org=acme, is_built_in=False)
        RolePermission.objects.create(role=role, resource_type=resource_type.value, permissions=int(bits))
        user = django_user_model.objects.create_user(email=f"bin-{label}@example.com", password="StrongPass123!")
        OrganizationUser.objects.create(user=user, org=acme, role=role)
        client = client_as(user)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
        return client

    return _make


@pytest.fixture
def viewer_client(client_as, django_user_model, acme, role_viewer):
    user = django_user_model.objects.create_user(email="bin-viewer@example.com", password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=acme, role=role_viewer)
    client = client_as(user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


def _bin(client, list_url):
    response = client.get(f"{list_url}recycle-bin/")
    assert response.status_code == 200, response.content
    return response.json()


def _backdate(model, row, days):
    model.all_objects.filter(pk=row.pk).update(soft_deleted_at=timezone.now() - timedelta(days=days))


@pytest.mark.django_db
class TestFlowRecycleBin:
    def test_bin_lists_deleted_flows_newest_first(self, admin_client, acme):
        older = Graph.objects.create(org=acme, name="Older")
        newer = Graph.objects.create(org=acme, name="Newer")
        Graph.objects.create(org=acme, name="Still live")
        older.delete()
        newer.delete()
        Graph.all_objects.filter(pk=older.pk).update(soft_deleted_at=timezone.now() - timedelta(hours=1))

        entries = _bin(admin_client, FLOWS_URL)

        assert [entry["id"] for entry in entries] == [newer.pk, older.pk]
        assert entries[0]["name"] == "Newer"
        assert set(entries[0]) == {"id", "name", "deleted_at", "days_left", "nodes"}

    def test_days_left_counts_down_from_the_retention_time(self, admin_client, acme):
        fresh = Graph.objects.create(org=acme, name="Fresh")
        five_days_old = Graph.objects.create(org=acme, name="Five days old")
        overdue = Graph.objects.create(org=acme, name="Overdue")
        for graph in (fresh, five_days_old, overdue):
            graph.delete()
        _backdate(Graph, five_days_old, days=5)
        _backdate(Graph, overdue, days=9)

        days_left = {entry["id"]: entry["days_left"] for entry in _bin(admin_client, FLOWS_URL)}

        assert days_left == {fresh.pk: 7, five_days_old.pk: 2, overdue.pk: 0}

    def test_days_left_follows_the_retention_setting(self, admin_client, acme, settings):
        settings.RECYCLE_BIN_RETENTION_DAYS = 30
        Graph.objects.create(org=acme, name="Long stay").delete()

        assert _bin(admin_client, FLOWS_URL)[0]["days_left"] == 30

    def test_restore_brings_the_flow_back(self, admin_client, acme):
        graph = Graph.objects.create(org=acme, name="Comeback")
        TaskNode.objects.create(graph=graph, node_name="task")
        assert admin_client.delete(f"{FLOWS_URL}{graph.pk}/").status_code == 204

        response = admin_client.post(f"{FLOWS_URL}{graph.pk}/restore/")

        assert response.status_code == 200, response.content
        assert response.json() == {"id": graph.pk, "name": "Comeback", "renamed_from": None}
        assert admin_client.get(f"{FLOWS_URL}{graph.pk}/").status_code == 200
        assert TaskNode.objects.filter(graph=graph).count() == 1
        assert _bin(admin_client, FLOWS_URL) == []

    def test_restore_renames_when_the_name_is_taken(self, admin_client, acme):
        graph = Graph.objects.create(org=acme, name="Report")
        graph.delete()
        Graph.objects.create(org=acme, name="Report")

        response = admin_client.post(f"{FLOWS_URL}{graph.pk}/restore/")

        assert response.status_code == 200, response.content
        assert response.json() == {"id": graph.pk, "name": "Report #2", "renamed_from": "Report"}

    def test_purge_removes_the_flow_for_good(self, admin_client, acme):
        graph = Graph.objects.create(org=acme, name="Gone")
        TaskNode.objects.create(graph=graph, node_name="task")
        graph.delete()

        response = admin_client.delete(f"{FLOWS_URL}{graph.pk}/purge/")

        assert response.status_code == 204, response.content
        assert not Graph.all_objects.filter(pk=graph.pk).exists()
        assert not TaskNode.all_objects.filter(graph_id=graph.pk).exists()
        assert admin_client.post(f"{FLOWS_URL}{graph.pk}/restore/").status_code == 404

    def test_restoring_a_flow_re_registers_its_telegram_trigger(
        self, admin_client, acme, mock_telegram_service, redis_client_mock
    ):
        graph = Graph.objects.create(org=acme, name="Telegram flow")
        node = TelegramTriggerNode.objects.create(graph=graph, node_name="bot")
        assert admin_client.delete(f"{FLOWS_URL}{graph.pk}/").status_code == 204
        mock_telegram_service.reset_mock()

        response = admin_client.post(f"{FLOWS_URL}{graph.pk}/restore/")

        assert response.status_code == 200, response.content
        mock_telegram_service.assert_called_once()
        registered = mock_telegram_service.call_args.kwargs["telegram_trigger_instance"]
        assert registered.pk == node.pk
        assert registered.active is True

    def test_other_orgs_flows_are_hidden_and_404(self, admin_client, beta):
        foreign = Graph.objects.create(org=beta, name="Foreign")
        foreign.delete()

        assert _bin(admin_client, FLOWS_URL) == []
        assert admin_client.post(f"{FLOWS_URL}{foreign.pk}/restore/").status_code == 404
        assert admin_client.delete(f"{FLOWS_URL}{foreign.pk}/purge/").status_code == 404
        assert Graph.deleted_objects.filter(pk=foreign.pk).exists()

    def test_live_flow_is_404_on_restore_and_purge(self, admin_client, acme):
        graph = Graph.objects.create(org=acme, name="Alive")

        assert admin_client.post(f"{FLOWS_URL}{graph.pk}/restore/").status_code == 404
        assert admin_client.delete(f"{FLOWS_URL}{graph.pk}/purge/").status_code == 404
        assert Graph.objects.filter(pk=graph.pk).exists()

    def test_flow_binned_before_batches_existed_is_hidden_and_404(self, admin_client, acme):
        legacy = Graph.objects.create(org=acme, name="Legacy")
        legacy.delete()
        Graph.all_objects.filter(pk=legacy.pk).update(soft_delete_batch=None)

        assert _bin(admin_client, FLOWS_URL) == []
        assert admin_client.post(f"{FLOWS_URL}{legacy.pk}/restore/").status_code == 404
        assert admin_client.delete(f"{FLOWS_URL}{legacy.pk}/purge/").status_code == 404
        assert Graph.deleted_objects.filter(pk=legacy.pk).exists()

    def test_non_numeric_id_is_404(self, admin_client):
        assert admin_client.post(f"{FLOWS_URL}not-a-number/restore/").status_code == 404
        assert admin_client.delete(f"{FLOWS_URL}not-a-number/purge/").status_code == 404


@pytest.fixture
def binned_flow(acme):
    graph = Graph.objects.create(org=acme, name="Guarded")
    graph.delete()
    return graph


@pytest.mark.django_db
class TestFlowRecycleBinPermissions:
    def test_read_only_lists_but_cannot_restore_or_purge(self, client_with_role, binned_flow):
        client = client_with_role(ResourceType.FLOWS, Permission.READ)

        assert [entry["id"] for entry in _bin(client, FLOWS_URL)] == [binned_flow.pk]
        assert client.post(f"{FLOWS_URL}{binned_flow.pk}/restore/").status_code == 403
        assert client.delete(f"{FLOWS_URL}{binned_flow.pk}/purge/").status_code == 403
        assert Graph.deleted_objects.filter(pk=binned_flow.pk).exists()

    def test_read_and_create_restores_but_cannot_purge(self, client_with_role, binned_flow):
        client = client_with_role(ResourceType.FLOWS, Permission.READ | Permission.CREATE)

        assert client.delete(f"{FLOWS_URL}{binned_flow.pk}/purge/").status_code == 403
        assert client.post(f"{FLOWS_URL}{binned_flow.pk}/restore/").status_code == 200
        assert Graph.objects.filter(pk=binned_flow.pk).exists()

    def test_read_and_delete_purges_but_cannot_restore(self, client_with_role, binned_flow):
        client = client_with_role(ResourceType.FLOWS, Permission.READ | Permission.DELETE)

        assert client.post(f"{FLOWS_URL}{binned_flow.pk}/restore/").status_code == 403
        assert client.delete(f"{FLOWS_URL}{binned_flow.pk}/purge/").status_code == 204
        assert not Graph.all_objects.filter(pk=binned_flow.pk).exists()

    def test_list_needs_read(self, client_with_role, binned_flow):
        client = client_with_role(ResourceType.FLOWS, Permission.CREATE | Permission.DELETE)

        assert client.get(f"{FLOWS_URL}recycle-bin/").status_code == 403

    @pytest.mark.parametrize(
        "bits, action",
        [
            (Permission.READ, None),
            (Permission.READ | Permission.CREATE, "restore"),
            (Permission.READ | Permission.DELETE, "purge"),
        ],
        ids=["read", "restore", "purge"],
    )
    def test_held_permission_still_404s_another_orgs_flow(self, client_with_role, beta, bits, action):
        foreign = Graph.objects.create(org=beta, name="Foreign")
        foreign.delete()
        client = client_with_role(ResourceType.FLOWS, bits)

        assert _bin(client, FLOWS_URL) == []
        if action == "restore":
            assert client.post(f"{FLOWS_URL}{foreign.pk}/restore/").status_code == 404
        if action == "purge":
            assert client.delete(f"{FLOWS_URL}{foreign.pk}/purge/").status_code == 404
        assert Graph.deleted_objects.filter(pk=foreign.pk).exists()

    def test_member_restores_but_cannot_purge(self, client_as, member_only, acme, binned_flow):
        client = client_as(member_only)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

        assert client.delete(f"{FLOWS_URL}{binned_flow.pk}/purge/").status_code == 403
        assert client.post(f"{FLOWS_URL}{binned_flow.pk}/restore/").status_code == 200

    def test_viewer_lists_but_cannot_restore(self, viewer_client, binned_flow):
        assert [entry["id"] for entry in _bin(viewer_client, FLOWS_URL)] == [binned_flow.pk]
        assert viewer_client.post(f"{FLOWS_URL}{binned_flow.pk}/restore/").status_code == 403

    def test_request_without_org_header_is_400(self, client_as, admin_acme):
        response = client_as(admin_acme).get(f"{FLOWS_URL}recycle-bin/")

        assert response.status_code == 400  # org_context_required


@pytest.mark.django_db
class TestRecycleBinSettings:
    def test_any_signed_in_user_reads_the_retention_time(self, client_as, member_only):
        response = client_as(member_only).get(SETTINGS_URL)

        assert response.status_code == 200
        assert response.json() == {"retention_days": 7}

    def test_follows_the_setting(self, client_as, member_only, settings):
        settings.RECYCLE_BIN_RETENTION_DAYS = 14

        assert client_as(member_only).get(SETTINGS_URL).json() == {"retention_days": 14}

    def test_anonymous_gets_401(self):
        assert APIClient().get(SETTINGS_URL).status_code == 401


def _make_flow(org: Organization, name: str) -> Model:
    return Graph.objects.create(org=org, name=name)


def _make_python_tool(org: Organization, name: str) -> Model:
    code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    return PythonCodeTool.objects.create(name=name, description="d", python_code=code, org=org)


def _make_mcp_tool(org: Organization, name: str) -> Model:
    return McpTool.objects.create(name=name, org=org, transport="https://example.com/mcp", tool_name="some_tool")


def _make_agent(org: Organization, name: str) -> Model:
    return AgentDefinition.objects.create(organization=org, name=name, instructions="Do things.")


def _make_surface(org: Organization, name: str) -> Model:
    return Surface.objects.create(organization=org, name=name)


def _make_collection(org: Organization, name: str) -> Model:
    return SourceCollection.objects.create(org=org, collection_name=name)


@dataclass(frozen=True)
class BinCase:
    key: str
    url: str
    delete_status: int
    make: Callable[[Organization, str], Model]

    @property
    def model(self) -> type[Model]:
        return bin_resources()[self.key].model

    @property
    def resource_type(self) -> ResourceType:
        return bin_resources()[self.key].resource_type


CASES = [
    BinCase("flow", FLOWS_URL, 204, _make_flow),
    BinCase("python_tool", PYTHON_TOOLS_URL, 204, _make_python_tool),
    BinCase("mcp_tool", "/api/mcp-tools/", 204, _make_mcp_tool),
    BinCase("agent", AGENTS_URL, 204, _make_agent),
    BinCase("surface", SURFACES_URL, 204, _make_surface),
    BinCase("collection", "/api/source-collections/", 200, _make_collection),
]


@pytest.mark.django_db
@pytest.mark.parametrize("case", CASES, ids=[case.key for case in CASES])
class TestEveryBinResource:
    def test_delete_list_restore_delete_purge(self, case, admin_client, acme):
        name = f"Lifecycle {case.key}"
        row = case.make(acme, name)
        detail_url = f"{case.url}{row.pk}/"

        assert admin_client.delete(detail_url).status_code == case.delete_status
        entries = _bin(admin_client, case.url)
        assert [entry["id"] for entry in entries] == [row.pk]
        assert ("nodes" in entries[0]) is (case.key == "flow")

        restored = admin_client.post(f"{detail_url}restore/")
        assert restored.status_code == 200, restored.content
        assert restored.json() == {"id": row.pk, "name": name, "renamed_from": None}
        assert admin_client.get(detail_url).status_code == 200
        assert _bin(admin_client, case.url) == []

        assert admin_client.delete(detail_url).status_code == case.delete_status
        purged = admin_client.delete(f"{detail_url}purge/")
        assert purged.status_code == 204, purged.content
        assert not case.model.all_objects.filter(pk=row.pk).exists()
        assert admin_client.post(f"{detail_url}restore/").status_code == 404

    def test_other_orgs_rows_are_hidden_and_404(self, case, admin_client, beta):
        row = case.make(beta, f"Foreign {case.key}")
        row.delete()

        assert _bin(admin_client, case.url) == []
        assert admin_client.post(f"{case.url}{row.pk}/restore/").status_code == 404
        assert admin_client.delete(f"{case.url}{row.pk}/purge/").status_code == 404
        assert case.model.deleted_objects.filter(pk=row.pk).exists()

    def test_live_row_is_404_on_restore_and_purge(self, case, admin_client, acme):
        row = case.make(acme, f"Alive {case.key}")

        assert admin_client.post(f"{case.url}{row.pk}/restore/").status_code == 404
        assert admin_client.delete(f"{case.url}{row.pk}/purge/").status_code == 404
        assert case.model.objects.filter(pk=row.pk).exists()

    def test_row_binned_before_batches_existed_is_hidden_and_404(self, case, admin_client, acme):
        row = case.make(acme, f"Legacy {case.key}")
        row.delete()
        case.model.all_objects.filter(pk=row.pk).update(soft_delete_batch=None)

        assert _bin(admin_client, case.url) == []
        assert admin_client.post(f"{case.url}{row.pk}/restore/").status_code == 404
        assert admin_client.delete(f"{case.url}{row.pk}/purge/").status_code == 404
        assert case.model.deleted_objects.filter(pk=row.pk).exists()

    def test_split_permissions(self, case, client_with_role, acme):
        row = case.make(acme, f"Guarded {case.key}")
        row.delete()
        restore_url = f"{case.url}{row.pk}/restore/"
        purge_url = f"{case.url}{row.pk}/purge/"
        reader = client_with_role(case.resource_type, Permission.READ)
        restorer = client_with_role(case.resource_type, Permission.READ | Permission.CREATE)
        purger = client_with_role(case.resource_type, Permission.READ | Permission.DELETE)

        assert [entry["id"] for entry in _bin(reader, case.url)] == [row.pk]
        assert reader.post(restore_url).status_code == 403
        assert reader.delete(purge_url).status_code == 403
        assert restorer.delete(purge_url).status_code == 403
        assert purger.post(restore_url).status_code == 403
        assert case.model.deleted_objects.filter(pk=row.pk).exists()

        assert restorer.post(restore_url).status_code == 200
        case.model.objects.get(pk=row.pk).delete()
        assert purger.delete(purge_url).status_code == 204
        assert not case.model.all_objects.filter(pk=row.pk).exists()

    def test_held_permission_still_404s_another_orgs_row(self, case, client_with_role, beta):
        row = case.make(beta, f"Foreign guarded {case.key}")
        row.delete()
        restorer = client_with_role(case.resource_type, Permission.READ | Permission.CREATE)
        purger = client_with_role(case.resource_type, Permission.READ | Permission.DELETE)

        assert _bin(restorer, case.url) == []
        assert restorer.post(f"{case.url}{row.pk}/restore/").status_code == 404
        assert purger.delete(f"{case.url}{row.pk}/purge/").status_code == 404
        assert case.model.deleted_objects.filter(pk=row.pk).exists()


WIRED_VIEWSETS = [
    (GraphViewSet, "flow"),
    (PythonCodeToolViewSet, "python_tool"),
    (McpToolViewSet, "mcp_tool"),
    (AgentDefinitionViewSet, "agent"),
    (SurfaceViewSet, "surface"),
    (SourceCollectionViewSet, "collection"),
]


def test_every_bin_resource_has_a_viewset():
    assert {key for _, key in WIRED_VIEWSETS} == set(bin_resources())


@pytest.mark.parametrize("viewset, key", WIRED_VIEWSETS, ids=[key for _, key in WIRED_VIEWSETS])
def test_viewset_is_wired_to_its_bin(viewset, key):
    assert issubclass(viewset, RecycleBinActionsMixin)
    assert viewset.recycle_bin_resource_key == key
    assert viewset.rbac_resource_type == bin_resources()[key].resource_type
    for action_name, permission in RECYCLE_BIN_ACTION_MAP.items():
        assert viewset.rbac_action_map[action_name] == permission


@pytest.mark.django_db
def test_built_in_tools_never_show_in_an_org_bin(admin_client):
    code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    built_in = PythonCodeTool.objects.create(name="Bin built-in", description="d", python_code=code, built_in=True)
    # upload_tools deletes a built-in that left the manifest the same way.
    built_in.delete()

    assert _bin(admin_client, PYTHON_TOOLS_URL) == []
    assert admin_client.post(f"{PYTHON_TOOLS_URL}{built_in.pk}/restore/").status_code == 404
    assert admin_client.delete(f"{PYTHON_TOOLS_URL}{built_in.pk}/purge/").status_code == 404
    assert PythonCodeTool.deleted_objects.filter(pk=built_in.pk).exists()


@pytest.mark.django_db
class TestOwnedSurfaces:
    @staticmethod
    def _agent_with_surface(acme):
        agent = AgentDefinition.objects.create(organization=acme, name="Owner", instructions="Do things.")
        surface = Surface.objects.create(organization=acme, name="Owned", owner_agent=agent)
        return agent, surface

    def test_surface_binned_with_its_agent_is_hidden_and_404(self, admin_client, acme):
        agent, surface = self._agent_with_surface(acme)
        assert admin_client.delete(f"{AGENTS_URL}{agent.pk}/").status_code == 204

        assert _bin(admin_client, SURFACES_URL) == []
        assert admin_client.post(f"{SURFACES_URL}{surface.pk}/restore/").status_code == 404
        assert admin_client.delete(f"{SURFACES_URL}{surface.pk}/purge/").status_code == 404
        assert Surface.deleted_objects.filter(pk=surface.pk).exists()

        assert admin_client.post(f"{AGENTS_URL}{agent.pk}/restore/").status_code == 200
        assert Surface.objects.filter(pk=surface.pk, owner_agent=agent).exists()

    def test_owned_surface_deleted_alone_is_listed_while_its_agent_is_live(self, admin_client, acme):
        agent, surface = self._agent_with_surface(acme)
        assert admin_client.delete(f"{SURFACES_URL}{surface.pk}/").status_code == 204

        assert [entry["id"] for entry in _bin(admin_client, SURFACES_URL)] == [surface.pk]
        assert admin_client.post(f"{SURFACES_URL}{surface.pk}/restore/").status_code == 200
        assert Surface.objects.get(pk=surface.pk).owner_agent_id == agent.pk

    def test_owned_surface_is_hidden_once_its_agent_is_deleted_too(self, admin_client, acme):
        agent, surface = self._agent_with_surface(acme)
        assert admin_client.delete(f"{SURFACES_URL}{surface.pk}/").status_code == 204
        assert admin_client.delete(f"{AGENTS_URL}{agent.pk}/").status_code == 204

        assert _bin(admin_client, SURFACES_URL) == []
        assert admin_client.post(f"{SURFACES_URL}{surface.pk}/restore/").status_code == 404
        assert [entry["id"] for entry in _bin(admin_client, AGENTS_URL)] == [agent.pk]

        assert admin_client.post(f"{AGENTS_URL}{agent.pk}/restore/").status_code == 200
        assert [entry["id"] for entry in _bin(admin_client, SURFACES_URL)] == [surface.pk]


# frontend/src/app/shared/models/node/node-type.ts
FRONTEND_NODE_TYPES = {
    "agent",
    "task",
    "tool",
    "llm",
    "python",
    "edge",
    "start",
    "table",
    "classification-decision-table",
    "note",
    "file-extractor",
    "webhook-trigger",
    "telegram-trigger",
    "end",
    "subgraph",
    "audio-to-text-node",
    "schedule-trigger",
    "knowledge-retriever",
    "key-value",
}


def _flow_with_nodes(org, name):
    graph = Graph.objects.create(org=org, name=name)
    StartNode.objects.create(graph=graph)
    PythonNode.objects.create(
        graph=graph,
        node_name="Parse",
        python_code=PythonCode.objects.create(code="def main(): return 1", entrypoint="main"),
    )
    TaskNode.objects.create(graph=graph, node_name="Write")
    AgentNode.objects.create(graph=graph, node_name="Writer")
    return graph


@pytest.mark.django_db
class TestFlowBinNodes:
    def test_lists_named_nodes_of_the_same_batch(self, admin_client, acme):
        graph = _flow_with_nodes(acme, "With nodes")
        binned_earlier = TaskNode.objects.create(graph=graph, node_name="Old")
        TaskNode.all_objects.filter(pk=binned_earlier.pk).update(
            active=False, soft_deleted_at=timezone.now(), soft_delete_batch=uuid.uuid4()
        )
        graph.delete()

        nodes = _bin(admin_client, FLOWS_URL)[0]["nodes"]

        assert sorted(nodes, key=lambda node: node["name"]) == [
            {"name": "Parse", "node_type": "python"},
            {"name": "Write", "node_type": "task"},
            {"name": "Writer", "node_type": "agent"},
        ]

    def test_query_count_does_not_grow_with_flows(self, admin_client, acme):
        _flow_with_nodes(acme, "First").delete()
        with CaptureQueriesContext(connection) as one_flow:
            _bin(admin_client, FLOWS_URL)
        for name in ("Second", "Third"):
            _flow_with_nodes(acme, name).delete()

        with CaptureQueriesContext(connection) as three_flows:
            entries = _bin(admin_client, FLOWS_URL)

        assert len(entries) == 3
        assert len(three_flows.captured_queries) == len(one_flow.captured_queries)

    def test_node_types_are_frontend_values(self):
        assert set(FLOW_BIN_NODE_TYPES.values()) <= FRONTEND_NODE_TYPES


def _has_node_name_column(model) -> bool:
    try:
        return model._meta.get_field("node_name").concrete
    except FieldDoesNotExist:
        return False


def test_every_named_flow_node_model_has_a_node_type():
    named_node_models = {
        model
        for model in apps.get_models()
        if any(field.name == "graph" and field.related_model is Graph for field in model._meta.concrete_fields)
        and _has_node_name_column(model)
    }

    assert named_node_models - {CrewNode} == set(FLOW_BIN_NODE_TYPES)
