"""Recycle-bin endpoints: list, restore and purge. Scoped to the active org.
READ lists, CREATE restores, DELETE purges."""

import uuid
from collections.abc import Callable
from types import SimpleNamespace
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

from agents.models import (
    AgentDefinition,
    Surface,
    SurfaceKnowledge,
    SurfaceMcpTool,
    SurfacePythonTool,
    ToolMode,
)
from agents.views.agent_definition_views import AgentDefinitionViewSet
from agents.views.surface_views import SurfaceViewSet
from rbac.identity.api_keys.principals import SystemServicePrincipal
from rbac.models import ApiKey, Organization, OrganizationUser, Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from tables.models import (
    AgentNode,
    KeyValueTable,
    KeyValueTableEntry,
    BaseRagType,
    DocumentContent,
    DocumentMetadata,
    CrewNode,
    Graph,
    PythonCode,
    PythonCodeTool,
    PythonNode,
    RealtimeChannel,
    Secret,
    WebhookTrigger,
    SourceCollection,
    StartNode,
    TaskNode,
)
from tables.models.graph_models import TelegramTriggerNode
from tables.exceptions import KeyValueTableNotFoundError
from tables.models.graph_models import KeyValueNode
from tables.models.knowledge_models import GraphRag
from tables.services.key_value_table_service import KeyValueTableService
from tables.models.mcp_models import McpTool
from tables.services.recycle_bin.bin_contents_service import CONTENTS_LIMIT, FLOW_BIN_NODE_TYPES
from tables.services.recycle_bin.registry import bin_resources
from tables.services.secrets.secret_service import secret_service
from tables.views.knowledge_views.collection_management_views import SourceCollectionViewSet
from tables.views.model_view_sets import (
    GraphViewSet,
    KeyValueTableViewSet,
    McpToolViewSet,
    PythonCodeToolViewSet,
    RealtimeChannelViewSet,
    SecretViewSet,
    WebhookTriggerViewSet,
)
from tables.views.recycle_bin_mixins import RECYCLE_BIN_ACTION_MAP, RecycleBinActionsMixin, request_actor
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from utils.logger import logger

FLOWS_URL = "/api/graphs/"
PYTHON_TOOLS_URL = "/api/python-code-tool/"
AGENTS_URL = "/api/agent-definitions/"
SURFACES_URL = "/api/surfaces/"
SETTINGS_URL = "/api/recycle-bin/settings/"
KEY_VALUE_TABLES_URL = "/api/key-value-tables/"


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
        assert set(entries[0]) == {"id", "name", "deleted_at", "days_left", "details", "contents", "contents_total"}

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

    def test_purge_is_logged_with_the_acting_user_and_ids_only(self, admin_client, admin_acme, acme):
        graph = Graph.objects.create(org=acme, name="Secret plan")
        graph.delete()
        batch = Graph.all_objects.get(pk=graph.pk).soft_delete_batch
        messages: list[str] = []
        sink_id = logger.add(messages.append, level="INFO", format="{message}")
        try:
            assert admin_client.delete(f"{FLOWS_URL}{graph.pk}/purge/").status_code == 204
        finally:
            logger.remove(sink_id)

        purge_lines = [message for message in messages if message.startswith("Purged ")]
        assert purge_lines == [f"Purged Graph {graph.pk} of org {acme.id} (batch {batch}) by user {admin_acme.pk}\n"]
        assert "Secret plan" not in "".join(messages)

    def test_non_numeric_id_is_404(self, admin_client):
        assert admin_client.post(f"{FLOWS_URL}not-a-number/restore/").status_code == 404
        assert admin_client.delete(f"{FLOWS_URL}not-a-number/purge/").status_code == 404


class TestPurgeActor:
    def test_a_signed_in_user(self):
        request = SimpleNamespace(user=SimpleNamespace(pk=7), auth=None)

        assert request_actor(request) == "user 7"

    def test_a_user_api_key(self):
        request = SimpleNamespace(user=SimpleNamespace(pk=7), auth=ApiKey(pk=3))

        assert request_actor(request) == "user 7 via API key 3"

    def test_a_system_api_key_has_no_user_pk(self):
        request = SimpleNamespace(user=SystemServicePrincipal(), auth=ApiKey(pk=4))

        assert request_actor(request) == "system-service via API key 4"


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
    return AgentDefinition.objects.create(organization=org, name=name, instruction_list=[{"name": "Instruction_1.md", "content": "Do things."}])


def _make_surface(org: Organization, name: str) -> Model:
    return Surface.objects.create(organization=org, name=name)


def _make_key_value_table(org: Organization, name: str) -> Model:
    return KeyValueTable.objects.create(org=org, name=name)


def _make_secret(org: Organization, name: str) -> Model:
    return secret_service.create(text="value", org=org, name=name)


def _make_realtime_channel(org: Organization, name: str) -> Model:
    return RealtimeChannel.objects.create(org=org, name=name)


def _make_webhook_trigger(org: Organization, name: str) -> Model:
    # The ORM skips the path validator, and every test here uses its own name.
    return WebhookTrigger.objects.create(org=org, path=name)


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
    BinCase("key_value_table", KEY_VALUE_TABLES_URL, 204, _make_key_value_table),
    BinCase("secret", "/api/secrets/", 204, _make_secret),
    BinCase("realtime_channel", "/api/realtime-channels/", 204, _make_realtime_channel),
    BinCase("webhook_trigger", "/api/webhook-triggers/", 204, _make_webhook_trigger),
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
        assert {"details", "contents", "contents_total"} <= set(entries[0])

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


@pytest.mark.django_db
@pytest.mark.parametrize("case", CASES, ids=[case.key for case in CASES])
class TestBulkActions:
    def test_restore_selected(self, case, admin_client, acme):
        rows = [case.make(acme, f"Bulk {case.key} {index}") for index in range(3)]
        for row in rows:
            row.delete()

        response = admin_client.post(
            f"{case.url}recycle-bin/restore/", {"ids": [rows[0].pk, rows[1].pk]}, format="json"
        )

        assert response.status_code == 200, response.content
        assert {item["id"] for item in response.json()["restored"]} == {rows[0].pk, rows[1].pk}
        assert response.json()["failed"] == []
        assert case.model.deleted_objects.filter(pk=rows[2].pk).exists()

    def test_empty_the_bin(self, case, admin_client, acme, beta):
        ours = [case.make(acme, f"Empty {case.key} {index}") for index in range(2)]
        theirs = case.make(beta, f"Theirs {case.key}")
        for row in [*ours, theirs]:
            row.delete()

        response = admin_client.post(f"{case.url}recycle-bin/purge/", {"all": True}, format="json")

        assert response.status_code == 200, response.content
        assert sorted(response.json()["purged"]) == sorted(row.pk for row in ours)
        assert not case.model.all_objects.filter(pk__in=[row.pk for row in ours]).exists()
        assert case.model.deleted_objects.filter(pk=theirs.pk).exists()

    def test_another_orgs_id_is_404_and_nothing_changes(self, case, admin_client, acme, beta):
        ours = case.make(acme, f"Ours {case.key}")
        theirs = case.make(beta, f"Theirs {case.key}")
        ours.delete()
        theirs.delete()

        response = admin_client.post(
            f"{case.url}recycle-bin/purge/", {"ids": [ours.pk, theirs.pk]}, format="json"
        )

        assert response.status_code == 404
        assert case.model.deleted_objects.filter(pk__in=[ours.pk, theirs.pk]).count() == 2

    def test_bulk_actions_need_their_bits(self, case, client_with_role, acme):
        row = case.make(acme, f"Guarded bulk {case.key}")
        row.delete()
        restorer = client_with_role(case.resource_type, Permission.READ | Permission.CREATE)
        purger = client_with_role(case.resource_type, Permission.READ | Permission.DELETE)

        assert restorer.post(f"{case.url}recycle-bin/purge/", {"all": True}, format="json").status_code == 403
        assert purger.post(f"{case.url}recycle-bin/restore/", {"all": True}, format="json").status_code == 403
        assert case.model.deleted_objects.filter(pk=row.pk).exists()

WIRED_VIEWSETS = [
    (GraphViewSet, "flow"),
    (PythonCodeToolViewSet, "python_tool"),
    (McpToolViewSet, "mcp_tool"),
    (AgentDefinitionViewSet, "agent"),
    (SurfaceViewSet, "surface"),
    (SourceCollectionViewSet, "collection"),
    (KeyValueTableViewSet, "key_value_table"),
    (SecretViewSet, "secret"),
    (RealtimeChannelViewSet, "realtime_channel"),
    (WebhookTriggerViewSet, "webhook_trigger"),
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
        agent = AgentDefinition.objects.create(organization=acme, name="Owner", instruction_list=[{"name": "Instruction_1.md", "content": "Do things."}])
        surface = Surface.objects.create(organization=acme, name="Owned", owner_agent=agent)
        return agent, surface

    def test_surface_binned_with_its_agent_is_listed_and_restores_shared(self, admin_client, acme):
        agent, surface = self._agent_with_surface(acme)
        assert admin_client.delete(f"{AGENTS_URL}{agent.pk}/").status_code == 204

        assert [entry["id"] for entry in _bin(admin_client, SURFACES_URL)] == [surface.pk]
        response = admin_client.post(f"{SURFACES_URL}{surface.pk}/restore/")

        assert response.status_code == 200, response.content
        assert Surface.objects.get(pk=surface.pk).owner_agent_id is None
        assert [entry["id"] for entry in _bin(admin_client, AGENTS_URL)] == [agent.pk]

    def test_surface_binned_with_its_agent_can_be_purged_alone(self, admin_client, acme):
        agent, surface = self._agent_with_surface(acme)
        admin_client.delete(f"{AGENTS_URL}{agent.pk}/")

        assert admin_client.delete(f"{SURFACES_URL}{surface.pk}/purge/").status_code == 204

        assert not Surface.all_objects.filter(pk=surface.pk).exists()
        assert AgentDefinition.deleted_objects.filter(pk=agent.pk).exists()

    def test_restoring_the_agent_brings_its_surface_back_as_its_own(self, admin_client, acme):
        agent, surface = self._agent_with_surface(acme)
        admin_client.delete(f"{AGENTS_URL}{agent.pk}/")

        assert admin_client.post(f"{AGENTS_URL}{agent.pk}/restore/").status_code == 200

        assert Surface.objects.filter(pk=surface.pk, owner_agent=agent).exists()

    def test_owned_surface_deleted_alone_is_listed_while_its_agent_is_live(self, admin_client, acme):
        agent, surface = self._agent_with_surface(acme)
        assert admin_client.delete(f"{SURFACES_URL}{surface.pk}/").status_code == 204

        assert [entry["id"] for entry in _bin(admin_client, SURFACES_URL)] == [surface.pk]
        assert admin_client.post(f"{SURFACES_URL}{surface.pk}/restore/").status_code == 200
        assert Surface.objects.get(pk=surface.pk).owner_agent_id == agent.pk

    def test_owned_surface_deleted_before_its_agent_is_listed_and_restores_shared(self, admin_client, acme):
        agent, surface = self._agent_with_surface(acme)
        assert admin_client.delete(f"{SURFACES_URL}{surface.pk}/").status_code == 204
        assert admin_client.delete(f"{AGENTS_URL}{agent.pk}/").status_code == 204

        assert [entry["id"] for entry in _bin(admin_client, SURFACES_URL)] == [surface.pk]
        assert admin_client.post(f"{SURFACES_URL}{surface.pk}/restore/").status_code == 200
        assert Surface.objects.get(pk=surface.pk).owner_agent_id is None
        assert [entry["id"] for entry in _bin(admin_client, AGENTS_URL)] == [agent.pk]


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

        entry = _bin(admin_client, FLOWS_URL)[0]

        assert entry["contents_total"] == 3
        assert sorted(entry["contents"], key=lambda content: content["name"]) == [
            {"name": "Parse", "kind": "python"},
            {"name": "Write", "kind": "task"},
            {"name": "Writer", "kind": "agent"},
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


@pytest.mark.django_db
class TestBinContents:
    """Each row lists what its restore brings back, from the same batch."""

    def test_an_agent_lists_its_own_surfaces(self, admin_client, acme):
        agent = AgentDefinition.objects.create(organization=acme, name="Owner", instruction_list=[{"name": "Instruction_1.md", "content": "x"}])
        Surface.objects.create(organization=acme, name="Own surface", owner_agent=agent)
        Surface.objects.create(organization=acme, name="Shared surface")
        admin_client.delete(f"{AGENTS_URL}{agent.pk}/")

        entry = _bin(admin_client, AGENTS_URL)[0]

        assert entry["contents"] == [{"name": "Own surface", "kind": "surface"}]
        assert entry["contents_total"] == 1

    def test_a_surface_lists_its_tools_and_sources(self, admin_client, acme):
        surface = Surface.objects.create(organization=acme, name="Research")
        tool = _make_python_tool(acme, "Search tool")
        mcp_tool = _make_mcp_tool(acme, "Web MCP")
        collection = SourceCollection.objects.create(org=acme, collection_name="Docs")
        SurfacePythonTool.objects.create(surface=surface, python_tool=tool, mode=ToolMode.ALLOW)
        SurfaceMcpTool.objects.create(surface=surface, mcp_tool=mcp_tool, mode=ToolMode.ALLOW)
        SurfaceKnowledge.objects.create(surface=surface, collection=collection)
        admin_client.delete(f"{SURFACES_URL}{surface.pk}/")

        contents = _bin(admin_client, SURFACES_URL)[0]["contents"]

        assert sorted((content["kind"], content["name"]) for content in contents) == [
            ("knowledge_source", "Docs"),
            ("mcp_tool", "Web MCP"),
            ("python_tool", "Search tool"),
        ]

    def test_a_collection_lists_its_documents(self, admin_client, acme):
        collection = SourceCollection.objects.create(org=acme, collection_name="Docs")
        content = DocumentContent.objects.create(content=b"x")
        DocumentMetadata.objects.create(
            source_collection=collection, document_content=content, file_name="a.txt", file_type="txt", file_size=1
        )
        admin_client.delete(f"/api/source-collections/{collection.pk}/")

        entry = _bin(admin_client, "/api/source-collections/")[0]

        assert entry["contents"] == [{"name": "a.txt", "kind": "document"}]

    def test_items_deleted_earlier_on_their_own_are_not_listed(self, admin_client, acme):
        agent = AgentDefinition.objects.create(organization=acme, name="Owner", instruction_list=[{"name": "Instruction_1.md", "content": "x"}])
        earlier = Surface.objects.create(organization=acme, name="Deleted before", owner_agent=agent)
        earlier.delete()
        admin_client.delete(f"{AGENTS_URL}{agent.pk}/")

        assert _bin(admin_client, AGENTS_URL)[0]["contents"] == []

    def test_contents_are_capped_and_counted(self, admin_client, acme):
        graph = Graph.objects.create(org=acme, name="Big")
        TaskNode.objects.bulk_create(
            [TaskNode(graph=graph, node_name=f"task {index}") for index in range(CONTENTS_LIMIT + 5)]
        )
        graph.delete()

        entry = _bin(admin_client, FLOWS_URL)[0]

        assert len(entry["contents"]) == CONTENTS_LIMIT
        assert entry["contents_total"] == CONTENTS_LIMIT + 5

    def test_show_all_returns_every_content_past_the_cap(self, admin_client, acme, beta):
        graph = Graph.objects.create(org=acme, name="Big")
        TaskNode.objects.bulk_create(
            [TaskNode(graph=graph, node_name=f"task {index}") for index in range(CONTENTS_LIMIT + 5)]
        )
        graph.delete()
        theirs = Graph.objects.create(org=beta, name="Theirs")
        theirs.delete()

        response = admin_client.get(f"{FLOWS_URL}{graph.pk}/recycle-bin-contents/")

        assert response.status_code == 200, response.content
        assert len(response.json()["contents"]) == CONTENTS_LIMIT + 5
        assert response.json()["contents_total"] == CONTENTS_LIMIT + 5
        assert admin_client.get(f"{FLOWS_URL}{theirs.pk}/recycle-bin-contents/").status_code == 404

    def test_tools_have_nothing_inside(self, admin_client, acme):
        _make_python_tool(acme, "Alone").delete()

        entry = _bin(admin_client, PYTHON_TOOLS_URL)[0]

        assert (entry["contents"], entry["contents_total"]) == ([], 0)


def _details(entry) -> dict:
    return {detail["label"]: (detail["value"], detail["format"]) for detail in entry["details"]}


@pytest.mark.django_db
class TestBinDetails:
    """Basic info about each binned item, shown when its row is expanded."""

    def test_a_secret_shows_where_it_is_used_never_its_value(
        self, admin_client, acme, llm_config
    ):
        secret = secret_service.create(text="sk-abcd1234", org=acme, name="OPENAI_KEY")
        llm_config.org = acme
        llm_config.api_key_secret = secret
        llm_config.save()
        admin_client.delete(f"/api/secrets/{secret.pk}/")

        entry = _bin(admin_client, "/api/secrets/")[0]
        details = _details(entry)

        assert list(details) == ["Created", "Last changed", "Used by"]
        assert details["Used by"] == ("1", "text")
        assert "sk-abcd1234" not in str(entry)
        assert Secret.all_objects.get(pk=secret.pk).value not in str(entry)

    def test_an_agent_shows_description_instructions_and_llm(self, admin_client, acme, llm_config):
        agent = AgentDefinition.objects.create(
            organization=acme,
            name="Helper",
            description="Answers support questions",
            instruction_list=[{"name": "Instruction_1.md", "content": "  Be   brief.\nUse the FAQ.  "}],
            llm_config=llm_config,
        )
        admin_client.delete(f"{AGENTS_URL}{agent.pk}/")

        details = _details(_bin(admin_client, AGENTS_URL)[0])

        assert details["Description"] == ("Answers support questions", "text")
        # Trimmed, with its own line breaks (the table shows them).
        assert details["Instructions"] == ("Be   brief.\nUse the FAQ.", "text")
        assert details["LLM"] == (f"MyGPT-4o · {llm_config.model.name}", "text")

    def test_an_agent_shows_its_instructions_in_order_without_blank_ones(self, admin_client, acme):
        agent = AgentDefinition.objects.create(
            organization=acme,
            name="Layered",
            instruction_list=[
                {"name": "Tone.md", "content": "Be kind."},
                {"name": "Empty.md", "content": "  "},
                {"name": "Goals.md", "content": "Close tickets."},
            ],
        )
        admin_client.delete(f"{AGENTS_URL}{agent.pk}/")

        details = _details(_bin(admin_client, AGENTS_URL)[0])

        assert details["Instructions"] == ("Be kind.\n\nClose tickets.", "text")

    def test_empty_fields_are_sent_as_null_and_long_instructions_whole(self, admin_client, acme):
        agent = AgentDefinition.objects.create(organization=acme, name="Terse", instruction_list=[{"name": "Instruction_1.md", "content": "x" * 500}])
        admin_client.delete(f"{AGENTS_URL}{agent.pk}/")

        details = _details(_bin(admin_client, AGENTS_URL)[0])

        assert list(details) == ["Description", "Instructions", "LLM"]
        assert details["Description"] == (None, "text")
        assert details["LLM"] == (None, "text")
        assert details["Instructions"] == ("x" * 500, "text")

    def test_a_description_is_sent_whole(self, admin_client, acme):
        description = "word_" * 100  # 500 characters
        agent = AgentDefinition.objects.create(
            organization=acme, name="Wordy", description=description, instruction_list=[{"name": "Instruction_1.md", "content": "x"}]
        )
        admin_client.delete(f"{AGENTS_URL}{agent.pk}/")

        details = _details(_bin(admin_client, AGENTS_URL)[0])

        assert details["Description"] == (description, "text")

    def test_a_flow_shows_its_dates(self, admin_client, acme):
        Graph.objects.create(org=acme, name="Dated", description="Nightly report").delete()

        details = _details(_bin(admin_client, FLOWS_URL)[0])

        assert details["Description"] == ("Nightly report", "text")
        assert details["Created"][1] == "date"
        assert details["Last changed"][1] == "date"

    def test_an_mcp_tool_shows_its_server_and_never_its_secret(self, admin_client, acme):
        _make_mcp_tool(acme, "Web").delete()

        entry = _bin(admin_client, "/api/mcp-tools/")[0]

        details = _details(entry)
        assert details["Server"] == ("https://example.com/mcp", "text")
        assert details["Tool name"] == ("some_tool", "text")
        assert list(details) == ["Server", "Tool name", "Created", "Last changed"]
        assert all("secret" not in label.lower() for label in details)

    def test_a_collection_shows_its_indexes_instead_of_upload_status(self, admin_client, acme):
        collection = SourceCollection.objects.create(org=acme, collection_name="Docs")
        BaseRagType.objects.create(rag_type=BaseRagType.RagType.GRAPH, source_collection=collection)
        GraphRag.objects.create(
            base_rag_type=BaseRagType.objects.get(source_collection=collection),
            rag_status=GraphRag.GraphRagStatus.COMPLETED,
        )
        admin_client.delete(f"/api/source-collections/{collection.pk}/")

        details = _details(_bin(admin_client, "/api/source-collections/")[0])

        assert details["Indexed"] == ("Naive RAG: Not indexed · GraphRAG: Indexed", "text")
        assert "Status" not in details

    def test_every_tab_sends_the_same_fields_for_every_row(self, admin_client, acme):
        Surface.objects.create(organization=acme, name="Bare").delete()
        Surface.objects.create(organization=acme, name="Full", instructions="Do it").delete()

        rows = _bin(admin_client, SURFACES_URL)

        assert {tuple(detail["label"] for detail in row["details"]) for row in rows} == {
            ("Instructions", "Owner agent", "Created", "Last changed")
        }

    def test_a_surface_whose_agent_is_binned_says_it_comes_back_shared(self, admin_client, acme):
        agent = AgentDefinition.objects.create(organization=acme, name="Owner", instruction_list=[{"name": "Instruction_1.md", "content": "x"}])
        Surface.objects.create(organization=acme, name="Own", owner_agent=agent)
        admin_client.delete(f"{AGENTS_URL}{agent.pk}/")

        details = _details(_bin(admin_client, SURFACES_URL)[0])

        assert details["Comes back as"][0].startswith("Shared")
        assert details["Comes back as"][1] == "notice"

    def test_an_owned_surface_names_its_agent(self, admin_client, acme):
        agent = AgentDefinition.objects.create(organization=acme, name="Owner", instruction_list=[{"name": "Instruction_1.md", "content": "x"}])
        surface = Surface.objects.create(organization=acme, name="Own", owner_agent=agent, instructions="Use docs")
        admin_client.delete(f"{SURFACES_URL}{surface.pk}/")

        details = _details(_bin(admin_client, SURFACES_URL)[0])

        assert details["Instructions"] == ("Use docs", "text")
        assert details["Owner agent"] == ("Owner", "text")
        assert details["Created"][1] == details["Last changed"][1] == "date"
        assert "Comes back as" not in details  # its agent is live


@pytest.mark.django_db
class TestKeyValueTableBin:
    def test_a_table_goes_with_its_keys_and_comes_back_with_them(self, admin_client, acme):
        table = KeyValueTable.objects.create(org=acme, name="Prices", description="Daily prices")
        entry = KeyValueTableEntry.objects.create(table=table, key="apple", value=1)
        admin_client.delete(f"{KEY_VALUE_TABLES_URL}{table.pk}/")

        row = _bin(admin_client, KEY_VALUE_TABLES_URL)[0]
        # Keys can be private data: the bin says how many come back, never which.
        assert (row["contents"], row["contents_total"]) == ([], 1)
        assert "Keys" not in _details(row)
        show_all = admin_client.get(f"{KEY_VALUE_TABLES_URL}{table.pk}/recycle-bin-contents/")
        assert show_all.json() == {"contents": [], "contents_total": 1}
        assert _details(row)["Description"] == ("Daily prices", "text")
        assert KeyValueTableEntry.deleted_objects.filter(pk=entry.pk).exists()

        assert admin_client.post(f"{KEY_VALUE_TABLES_URL}{table.pk}/restore/").status_code == 200
        assert KeyValueTableEntry.objects.filter(pk=entry.pk).exists()

    def test_a_binned_table_frees_its_name(self, admin_client, acme):
        KeyValueTable.objects.create(org=acme, name="Prices").delete()

        response = admin_client.post(KEY_VALUE_TABLES_URL, {"name": "Prices"}, format="json")

        assert response.status_code == 201, response.content

    def test_restore_renames_when_the_name_is_taken_in_another_case(self, admin_client, acme):
        table = KeyValueTable.objects.create(org=acme, name="Prices")
        table.delete()
        KeyValueTable.objects.create(org=acme, name="prices")

        response = admin_client.post(f"{KEY_VALUE_TABLES_URL}{table.pk}/restore/")

        assert response.status_code == 200, response.content
        assert response.json() == {"id": table.pk, "name": "Prices #2", "renamed_from": "Prices"}

    def test_flows_lose_the_deleted_table(self, admin_client, acme):
        table = KeyValueTable.objects.create(org=acme, name="Prices")
        graph = Graph.objects.create(org=acme, name="Uses prices")
        node = KeyValueNode.objects.create(graph=graph, node_name="kv", key_value_table=table)

        admin_client.delete(f"{KEY_VALUE_TABLES_URL}{table.pk}/")

        node.refresh_from_db()
        assert node.key_value_table_id is None

    def test_a_binned_table_takes_no_runtime_writes(self, acme):
        table = KeyValueTable.objects.create(org=acme, name="Prices")
        table.delete()

        with pytest.raises(KeyValueTableNotFoundError):
            KeyValueTableService().write(table, {"apple": 2})

        assert not KeyValueTableEntry.all_objects.filter(table=table).exists()
