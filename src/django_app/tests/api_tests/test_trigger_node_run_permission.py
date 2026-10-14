"""Creating or editing a trigger node (webhook, Telegram, schedule) needs flows:RUN.

A trigger node starts flow runs by itself, so the bulk flow save and the three
trigger node viewsets require RUN on top of the action's own flows bit. Deleting a
trigger node, and saving a flow without touching one, keep working without RUN.
"""

import pytest
from django.urls import reverse
from rest_framework import status

from rbac.models import OrganizationUser, Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from tables.models import Graph, PythonCode
from tables.models.graph_models import (
    PythonNode,
    ScheduleTriggerNode,
    TelegramTriggerNode,
    WebhookTriggerNode,
)
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

TRIGGER_CODE = "trigger_nodes_require_run_permission"
EDITOR = Permission.CREATE | Permission.READ | Permission.UPDATE | Permission.DELETE
PYTHON_CODE_DATA = {
    "code": "def main(**kwargs):\n    return None\n",
    "entrypoint": "main",
    "libraries": [],
    "global_kwargs": {},
}


def _client_with_flows_permissions(client_as, django_user_model, org, permissions, name):
    role = Role.objects.create(name=name, org=org, is_built_in=False)
    RolePermission.objects.create(
        role=role, resource_type=ResourceType.FLOWS, permissions=int(permissions)
    )
    user = django_user_model.objects.create_user(
        email=f"{name}@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org, role=role)
    client = client_as(user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.fixture(autouse=True)
def _no_telegram_calls(mock_telegram_service):
    """Telegram node saves register the bot with Telegram; never under test here."""


@pytest.fixture
def editor_client(client_as, django_user_model, acme):
    return _client_with_flows_permissions(
        client_as, django_user_model, acme, EDITOR, "trigger-editor-no-run"
    )


@pytest.fixture
def runner_editor_client(client_as, django_user_model, acme):
    return _client_with_flows_permissions(
        client_as, django_user_model, acme, EDITOR | Permission.RUN, "trigger-editor-run"
    )


@pytest.fixture
def acme_graph(acme):
    return Graph.objects.create(name="trigger-run-acme-flow", org=acme)


@pytest.fixture
def schedule_node(acme_graph):
    return ScheduleTriggerNode.objects.create(graph=acme_graph, node_name="Hourly")


@pytest.fixture
def webhook_node(acme_graph):
    return WebhookTriggerNode.objects.create(
        graph=acme_graph,
        node_name="Incoming",
        python_code=PythonCode.objects.create(code="def main(**kwargs): ..."),
    )


@pytest.fixture
def telegram_node(acme_graph):
    return TelegramTriggerNode.objects.create(graph=acme_graph, node_name="Bot")


def _save_url(graph):
    return reverse("graphs-save-flow", args=[graph.id])


def _assert_trigger_denied(response):
    assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
    assert response.data["code"] == TRIGGER_CODE


# ── POST /api/graphs/<id>/save/ ──────────────────────────────────────────────


@pytest.mark.django_db
class TestBulkSave:
    def test_creating_a_trigger_node_without_run_gets_403_and_writes_nothing(
        self, editor_client, acme_graph
    ):
        payload = {
            "save_version": acme_graph.save_version,
            "schedule_trigger_node_list": [{"graph": acme_graph.id, "node_name": "New"}],
            "python_node_list": [{"graph": acme_graph.id, "python_code": PYTHON_CODE_DATA}],
        }

        response = editor_client.post(_save_url(acme_graph), payload, format="json")

        _assert_trigger_denied(response)
        assert not ScheduleTriggerNode.objects.filter(graph=acme_graph).exists()
        assert not PythonNode.objects.filter(graph=acme_graph).exists()
        acme_graph.refresh_from_db()
        assert acme_graph.save_version == payload["save_version"]

    def test_moving_a_trigger_node_without_run_gets_403(
        self, editor_client, acme_graph, schedule_node
    ):
        payload = {
            "save_version": acme_graph.save_version,
            "schedule_trigger_node_list": [
                {
                    "id": schedule_node.id,
                    "graph": acme_graph.id,
                    "node_name": schedule_node.node_name,
                    "metadata": {"position": {"x": 10, "y": 20}},
                }
            ],
        }

        response = editor_client.post(_save_url(acme_graph), payload, format="json")

        _assert_trigger_denied(response)
        schedule_node.refresh_from_db()
        assert schedule_node.metadata != {"position": {"x": 10, "y": 20}}

    def test_saving_without_trigger_nodes_needs_no_run(self, editor_client, acme_graph):
        payload = {
            "save_version": acme_graph.save_version,
            "python_node_list": [{"graph": acme_graph.id, "python_code": PYTHON_CODE_DATA}],
        }

        response = editor_client.post(_save_url(acme_graph), payload, format="json")

        assert response.status_code == status.HTTP_200_OK, response.content
        assert PythonNode.objects.filter(graph=acme_graph).count() == 1

    def test_deleting_a_trigger_node_needs_no_run(self, editor_client, acme_graph, schedule_node):
        payload = {
            "save_version": acme_graph.save_version,
            "deleted": {"schedule_trigger_node_ids": [schedule_node.id]},
        }

        response = editor_client.post(_save_url(acme_graph), payload, format="json")

        assert response.status_code == status.HTTP_200_OK, response.content
        assert not ScheduleTriggerNode.objects.filter(pk=schedule_node.pk).exists()

    def test_creating_a_trigger_node_with_run_succeeds(self, runner_editor_client, acme_graph):
        payload = {
            "save_version": acme_graph.save_version,
            "schedule_trigger_node_list": [{"graph": acme_graph.id, "node_name": "New"}],
        }

        response = runner_editor_client.post(_save_url(acme_graph), payload, format="json")

        assert response.status_code == status.HTTP_200_OK, response.content
        assert ScheduleTriggerNode.objects.filter(graph=acme_graph, node_name="New").exists()

    def test_foreign_flow_is_404_not_the_trigger_403(self, editor_client, beta):
        beta_graph = Graph.objects.create(name="trigger-run-beta-flow", org=beta)
        payload = {
            "save_version": beta_graph.save_version,
            "schedule_trigger_node_list": [{"graph": beta_graph.id, "node_name": "New"}],
        }

        response = editor_client.post(_save_url(beta_graph), payload, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.content
        assert not ScheduleTriggerNode.objects.filter(graph=beta_graph).exists()


# ── /api/{webhook,telegram,schedule}-trigger-nodes/ ──────────────────────────

TRIGGER_VIEWSETS = [
    ("webhooktriggernode", "webhook_node"),
    ("telegramtriggernode", "telegram_node"),
    ("scheduletriggernode", "schedule_node"),
]


@pytest.mark.django_db
class TestTriggerNodeViewSets:
    @pytest.mark.parametrize(("basename", "node_fixture"), TRIGGER_VIEWSETS)
    def test_create_without_run_gets_403(
        self, request, editor_client, acme_graph, basename, node_fixture
    ):
        model = type(request.getfixturevalue(node_fixture))
        existing = model.objects.count()

        response = editor_client.post(
            reverse(f"{basename}-list"),
            {"graph": acme_graph.id, "node_name": "New trigger"},
            format="json",
        )

        _assert_trigger_denied(response)
        assert model.objects.count() == existing

    @pytest.mark.parametrize("method", ["put", "patch"])
    @pytest.mark.parametrize(("basename", "node_fixture"), TRIGGER_VIEWSETS)
    def test_update_without_run_gets_403(
        self, request, editor_client, acme_graph, basename, node_fixture, method
    ):
        node = request.getfixturevalue(node_fixture)

        response = getattr(editor_client, method)(
            reverse(f"{basename}-detail", args=[node.id]),
            {"graph": acme_graph.id, "node_name": "Renamed"},
            format="json",
        )

        _assert_trigger_denied(response)
        node.refresh_from_db()
        assert node.node_name != "Renamed"

    def test_register_webhook_without_run_gets_403(self, editor_client, telegram_node):
        response = editor_client.post(
            reverse("telegramtriggernode-register-webhook", args=[telegram_node.id])
        )

        _assert_trigger_denied(response)

    def test_register_webhook_with_run_passes_the_gate(self, runner_editor_client, telegram_node):
        response = runner_editor_client.post(
            reverse("telegramtriggernode-register-webhook", args=[telegram_node.id])
        )

        # The node has no bot key: the request reached the action itself.
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert response.data["code"] == "telegram_bot_key_not_configured"

    def test_schedule_create_update_partial_update_with_run_succeed(
        self, runner_editor_client, acme_graph
    ):
        created = runner_editor_client.post(
            reverse("scheduletriggernode-list"),
            {"graph": acme_graph.id, "node_name": "Daily"},
            format="json",
        )
        assert created.status_code == status.HTTP_201_CREATED, created.content
        detail_url = reverse("scheduletriggernode-detail", args=[created.data["id"]])

        replaced = runner_editor_client.put(
            detail_url, {"graph": acme_graph.id, "node_name": "Nightly"}, format="json"
        )
        patched = runner_editor_client.patch(detail_url, {"node_name": "Weekly"}, format="json")

        assert replaced.status_code == status.HTTP_200_OK, replaced.content
        assert patched.status_code == status.HTTP_200_OK, patched.content
        assert ScheduleTriggerNode.objects.get(pk=created.data["id"]).node_name == "Weekly"

    def test_webhook_create_with_run_succeeds(self, runner_editor_client, acme_graph):
        response = runner_editor_client.post(
            reverse("webhooktriggernode-list"),
            {
                "graph": acme_graph.id,
                "node_name": "Incoming order",
                "python_code": PYTHON_CODE_DATA,
                "metadata": {},
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content

    def test_run_without_update_still_cannot_edit(
        self, client_as, django_user_model, acme, schedule_node
    ):
        client = _client_with_flows_permissions(
            client_as, django_user_model, acme, Permission.READ | Permission.RUN, "trigger-runner"
        )

        response = client.patch(
            reverse("scheduletriggernode-detail", args=[schedule_node.id]),
            {"node_name": "Renamed"},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        assert response.data["code"] == "permission_denied"

    def test_read_and_delete_need_no_run(self, editor_client, schedule_node):
        detail_url = reverse("scheduletriggernode-detail", args=[schedule_node.id])

        listed = editor_client.get(reverse("scheduletriggernode-list"))
        retrieved = editor_client.get(detail_url)
        deleted = editor_client.delete(detail_url)

        assert listed.status_code == status.HTTP_200_OK, listed.content
        assert retrieved.status_code == status.HTTP_200_OK, retrieved.content
        assert deleted.status_code == status.HTTP_204_NO_CONTENT, deleted.content
        assert not ScheduleTriggerNode.objects.filter(pk=schedule_node.pk).exists()

    def test_superadmin_needs_no_role(self, client_as, superadmin, acme, acme_graph):
        client = client_as(superadmin)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

        response = client.post(
            reverse("scheduletriggernode-list"),
            {"graph": acme_graph.id, "node_name": "Admin schedule"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content
