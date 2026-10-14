"""Creating or editing a trigger node (webhook, Telegram, schedule) needs flows:RUN.

A trigger node starts flow runs by itself, so the bulk flow save and the three
trigger node viewsets require RUN on top of the action's own flows bit. Deleting a
trigger node, and saving a flow without touching one, keep working without RUN.
Another org's flow or node, and a missing id, are a 404 for every caller, before
any RUN 403.
"""

import pytest
from django.urls import reverse
from rest_framework import status

from rbac.models.enums import Permission, ResourceType
from tables.models import Graph, PythonCode
from tables.models.graph_models import (
    PythonNode,
    ScheduleTriggerNode,
    TelegramTriggerNode,
    WebhookTriggerNode,
)
from tables.services.telegram_trigger_service import TelegramTriggerService
from tests.custom_role_fixtures import *  # noqa: F401,F403
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

TRIGGER_CODE = "trigger_nodes_require_run_permission"
EDITOR = Permission.CREATE | Permission.READ | Permission.UPDATE | Permission.DELETE
PYTHON_CODE_DATA = {
    "code": "def main(**kwargs):\n    return None\n",
    "entrypoint": "main",
    "libraries": [],
    "global_kwargs": {},
}


@pytest.fixture(autouse=True)
def _no_telegram_calls(mock_telegram_service):
    """Telegram node saves register the bot with Telegram; never under test here."""


@pytest.fixture
def editor_client(custom_role_client, acme):
    return custom_role_client(acme, {ResourceType.FLOWS: EDITOR}, "trigger-editor-no-run")


@pytest.fixture
def runner_editor_client(custom_role_client, acme):
    return custom_role_client(
        acme, {ResourceType.FLOWS: EDITOR | Permission.RUN}, "trigger-editor-run"
    )


@pytest.fixture
def acme_graph(acme):
    return Graph.objects.create(name="trigger-run-acme-flow", org=acme)


def _webhook_node(graph):
    return WebhookTriggerNode.objects.create(
        graph=graph,
        node_name="Incoming",
        python_code=PythonCode.objects.create(code="def main(**kwargs): ..."),
    )


def _telegram_node(graph):
    return TelegramTriggerNode.objects.create(graph=graph, node_name="Bot")


def _schedule_node(graph):
    return ScheduleTriggerNode.objects.create(graph=graph, node_name="Hourly")


def _webhook_node_payload(graph):
    return {"graph": graph.id, "node_name": "New", "python_code": PYTHON_CODE_DATA, "metadata": {}}


def _telegram_node_payload(graph):
    return {"graph": graph.id, "node_name": "New", "fields": []}


def _plain_node_payload(graph):
    return {"graph": graph.id, "node_name": "New"}


# One row per trigger node type: its model, its bulk-save list, its viewset
# basename, a stored node and the body that creates one.
TRIGGER_TYPES = [
    pytest.param(
        WebhookTriggerNode,
        "webhook_trigger_node_list",
        "webhooktriggernode",
        _webhook_node,
        _webhook_node_payload,
        id="webhook",
    ),
    pytest.param(
        TelegramTriggerNode,
        "telegram_trigger_node_list",
        "telegramtriggernode",
        _telegram_node,
        _telegram_node_payload,
        id="telegram",
    ),
    pytest.param(
        ScheduleTriggerNode,
        "schedule_trigger_node_list",
        "scheduletriggernode",
        _schedule_node,
        _plain_node_payload,
        id="schedule",
    ),
]
TRIGGER_TYPE_ARGS = ("model", "list_key", "basename", "make_node", "make_payload")


def _save_url(graph):
    return reverse("graphs-save-flow", args=[graph.id])


def _assert_trigger_denied(response):
    assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
    assert response.data["code"] == TRIGGER_CODE


# ── POST /api/graphs/<id>/save/ ──────────────────────────────────────────────


@pytest.mark.django_db
class TestBulkSave:
    @pytest.mark.parametrize(TRIGGER_TYPE_ARGS, TRIGGER_TYPES)
    def test_creating_a_trigger_node_without_run_gets_403_and_writes_nothing(
        self, editor_client, acme_graph, model, list_key, basename, make_node, make_payload
    ):
        payload = {
            "save_version": acme_graph.save_version,
            list_key: [make_payload(acme_graph)],
            "python_node_list": [{"graph": acme_graph.id, "python_code": PYTHON_CODE_DATA}],
        }

        response = editor_client.post(_save_url(acme_graph), payload, format="json")

        _assert_trigger_denied(response)
        assert not model.objects.filter(graph=acme_graph).exists()
        assert not PythonNode.objects.filter(graph=acme_graph).exists()
        acme_graph.refresh_from_db()
        assert acme_graph.save_version == payload["save_version"]

    def test_moving_a_trigger_node_without_run_gets_403(self, editor_client, acme_graph):
        schedule_node = _schedule_node(acme_graph)
        metadata_before = schedule_node.metadata
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
        assert schedule_node.metadata == metadata_before

    def test_saving_without_trigger_nodes_needs_no_run(self, editor_client, acme_graph):
        payload = {
            "save_version": acme_graph.save_version,
            "python_node_list": [{"graph": acme_graph.id, "python_code": PYTHON_CODE_DATA}],
        }

        response = editor_client.post(_save_url(acme_graph), payload, format="json")

        assert response.status_code == status.HTTP_200_OK, response.content
        assert PythonNode.objects.filter(graph=acme_graph).count() == 1

    def test_deleting_a_trigger_node_needs_no_run(self, editor_client, acme_graph):
        schedule_node = _schedule_node(acme_graph)
        payload = {
            "save_version": acme_graph.save_version,
            "deleted": {"schedule_trigger_node_ids": [schedule_node.id]},
        }

        response = editor_client.post(_save_url(acme_graph), payload, format="json")

        assert response.status_code == status.HTTP_200_OK, response.content
        assert not ScheduleTriggerNode.objects.filter(pk=schedule_node.pk).exists()

    @pytest.mark.parametrize(TRIGGER_TYPE_ARGS, TRIGGER_TYPES)
    def test_creating_a_trigger_node_with_run_succeeds(
        self, runner_editor_client, acme_graph, model, list_key, basename, make_node, make_payload
    ):
        payload = {"save_version": acme_graph.save_version, list_key: [make_payload(acme_graph)]}

        response = runner_editor_client.post(_save_url(acme_graph), payload, format="json")

        assert response.status_code == status.HTTP_200_OK, response.content
        assert model.objects.filter(graph=acme_graph, node_name="New").exists()

    @pytest.mark.parametrize(
        ("flows_permissions", "expected_status"),
        [
            pytest.param(EDITOR, status.HTTP_403_FORBIDDEN, id="without-run"),
            pytest.param(EDITOR | Permission.RUN, status.HTTP_200_OK, id="with-run"),
        ],
    )
    def test_a_user_api_key_acts_with_its_owners_role(
        self, custom_role_client, acme, acme_graph, flows_permissions, expected_status
    ):
        client = custom_role_client(
            acme, {ResourceType.FLOWS: flows_permissions}, "bulk-key", via_api_key=True
        )
        payload = {
            "save_version": acme_graph.save_version,
            "schedule_trigger_node_list": [_plain_node_payload(acme_graph)],
        }

        response = client.post(_save_url(acme_graph), payload, format="json")

        assert response.status_code == expected_status, response.content
        if expected_status == status.HTTP_403_FORBIDDEN:
            assert response.data["code"] == TRIGGER_CODE
        assert ScheduleTriggerNode.objects.filter(graph=acme_graph).exists() == (
            expected_status == status.HTTP_200_OK
        )

    def test_superadmin_needs_no_role(self, org_client_as, superadmin, acme, acme_graph):
        payload = {
            "save_version": acme_graph.save_version,
            "schedule_trigger_node_list": [_plain_node_payload(acme_graph)],
        }

        response = org_client_as(superadmin, acme).post(
            _save_url(acme_graph), payload, format="json"
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        assert ScheduleTriggerNode.objects.filter(graph=acme_graph).exists()

    def test_foreign_flow_is_404_not_the_trigger_403(self, editor_client, beta):
        beta_graph = Graph.objects.create(name="trigger-run-beta-flow", org=beta)
        payload = {
            "save_version": beta_graph.save_version,
            "schedule_trigger_node_list": [_plain_node_payload(beta_graph)],
        }

        response = editor_client.post(_save_url(beta_graph), payload, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.content
        assert not ScheduleTriggerNode.objects.filter(graph=beta_graph).exists()


# ── /api/{webhook,telegram,schedule}-trigger-nodes/ ──────────────────────────


@pytest.mark.django_db
class TestTriggerNodeViewSets:
    @pytest.mark.parametrize("via_api_key", [False, True], ids=["session", "user-api-key"])
    @pytest.mark.parametrize(TRIGGER_TYPE_ARGS, TRIGGER_TYPES)
    def test_create_without_run_gets_403(
        self,
        custom_role_client,
        acme,
        acme_graph,
        model,
        list_key,
        basename,
        make_node,
        make_payload,
        via_api_key,
    ):
        client = custom_role_client(
            acme, {ResourceType.FLOWS: EDITOR}, "create-no-run", via_api_key=via_api_key
        )

        response = client.post(reverse(f"{basename}-list"), make_payload(acme_graph), format="json")

        _assert_trigger_denied(response)
        assert not model.objects.exists()

    @pytest.mark.parametrize("method", ["put", "patch"])
    @pytest.mark.parametrize(TRIGGER_TYPE_ARGS, TRIGGER_TYPES)
    def test_update_without_run_gets_403(
        self,
        editor_client,
        acme_graph,
        mock_telegram_service,
        model,
        list_key,
        basename,
        make_node,
        make_payload,
        method,
    ):
        node = make_node(acme_graph)
        mock_telegram_service.reset_mock()

        response = getattr(editor_client, method)(
            reverse(f"{basename}-detail", args=[node.id]),
            {"graph": acme_graph.id, "node_name": "Renamed"},
            format="json",
        )

        _assert_trigger_denied(response)
        node.refresh_from_db()
        assert node.node_name != "Renamed"
        mock_telegram_service.assert_not_called()

    @pytest.mark.parametrize(
        ("method", "body"),
        [
            pytest.param("put", {}, id="put-missing-fields"),
            pytest.param("patch", {"graph": "not-an-id"}, id="patch-invalid-field"),
            pytest.param(
                "patch", {"node_name": "Renamed", "content_hash": "stale"}, id="patch-stale-hash"
            ),
        ],
    )
    @pytest.mark.parametrize(TRIGGER_TYPE_ARGS, TRIGGER_TYPES)
    def test_without_run_any_body_on_an_own_node_gets_the_same_403(
        self,
        editor_client,
        acme_graph,
        model,
        list_key,
        basename,
        make_node,
        make_payload,
        method,
        body,
    ):
        """The RUN check comes before the body is validated and before the content
        hash precondition, so a caller without RUN always gets the RUN 403."""
        node = make_node(acme_graph)

        response = getattr(editor_client, method)(
            reverse(f"{basename}-detail", args=[node.id]), body, format="json"
        )

        _assert_trigger_denied(response)
        node.refresh_from_db()
        assert node.node_name != "Renamed"

    @pytest.mark.parametrize("client_fixture", ["editor_client", "runner_editor_client"])
    @pytest.mark.parametrize("method", ["put", "patch"])
    @pytest.mark.parametrize(TRIGGER_TYPE_ARGS, TRIGGER_TYPES)
    def test_another_orgs_node_or_a_missing_id_is_404_with_or_without_run(
        self,
        request,
        beta,
        model,
        list_key,
        basename,
        make_node,
        make_payload,
        method,
        client_fixture,
    ):
        client = request.getfixturevalue(client_fixture)
        node = make_node(Graph.objects.create(name="trigger-run-beta-flow", org=beta))
        body = {"graph": node.graph_id, "node_name": "Renamed"}

        foreign = getattr(client, method)(
            reverse(f"{basename}-detail", args=[node.id]), body, format="json"
        )
        missing = getattr(client, method)(
            reverse(f"{basename}-detail", args=[999_999]), body, format="json"
        )

        assert foreign.status_code == status.HTTP_404_NOT_FOUND, foreign.content
        assert missing.status_code == status.HTTP_404_NOT_FOUND, missing.content
        node.refresh_from_db()
        assert node.node_name != "Renamed"

    def test_register_webhook_without_run_gets_403_and_sends_nothing(
        self, editor_client, acme_graph, mocker
    ):
        register = mocker.patch.object(TelegramTriggerService, "register_webhook_explicitly")

        response = editor_client.post(
            reverse("telegramtriggernode-register-webhook", args=[_telegram_node(acme_graph).id])
        )

        _assert_trigger_denied(response)
        register.assert_not_called()

    def test_register_webhook_with_run_passes_the_gate(self, runner_editor_client, acme_graph):
        response = runner_editor_client.post(
            reverse("telegramtriggernode-register-webhook", args=[_telegram_node(acme_graph).id])
        )

        # The node has no bot key: the request reached the action itself.
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert response.data["code"] == "telegram_bot_key_not_configured"

    @pytest.mark.parametrize("client_fixture", ["editor_client", "runner_editor_client"])
    def test_register_webhook_on_another_orgs_node_or_a_missing_id_is_404(
        self, request, beta, mocker, client_fixture
    ):
        client = request.getfixturevalue(client_fixture)
        register = mocker.patch.object(TelegramTriggerService, "register_webhook_explicitly")
        node = _telegram_node(Graph.objects.create(name="trigger-run-beta-flow", org=beta))

        foreign = client.post(reverse("telegramtriggernode-register-webhook", args=[node.id]))
        missing = client.post(reverse("telegramtriggernode-register-webhook", args=[999_999]))

        assert foreign.status_code == status.HTTP_404_NOT_FOUND, foreign.content
        assert missing.status_code == status.HTTP_404_NOT_FOUND, missing.content
        register.assert_not_called()

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

    @pytest.mark.parametrize(TRIGGER_TYPE_ARGS, TRIGGER_TYPES)
    def test_create_with_run_succeeds(
        self,
        runner_editor_client,
        acme_graph,
        model,
        list_key,
        basename,
        make_node,
        make_payload,
    ):
        response = runner_editor_client.post(
            reverse(f"{basename}-list"), make_payload(acme_graph), format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content
        assert model.objects.filter(graph=acme_graph, node_name="New").exists()

    def test_create_with_a_run_api_key_succeeds(self, custom_role_client, acme, acme_graph):
        client = custom_role_client(
            acme, {ResourceType.FLOWS: EDITOR | Permission.RUN}, "create-run-key", via_api_key=True
        )

        response = client.post(
            reverse("scheduletriggernode-list"), _plain_node_payload(acme_graph), format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content

    def test_run_without_update_still_cannot_edit(self, custom_role_client, acme, acme_graph):
        schedule_node = _schedule_node(acme_graph)
        client = custom_role_client(
            acme, {ResourceType.FLOWS: Permission.READ | Permission.RUN}, "trigger-runner"
        )

        response = client.patch(
            reverse("scheduletriggernode-detail", args=[schedule_node.id]),
            {"node_name": "Renamed"},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        assert response.data["code"] == "permission_denied"

    def test_read_and_delete_need_no_run(self, editor_client, acme_graph):
        schedule_node = _schedule_node(acme_graph)
        detail_url = reverse("scheduletriggernode-detail", args=[schedule_node.id])

        listed = editor_client.get(reverse("scheduletriggernode-list"))
        retrieved = editor_client.get(detail_url)
        deleted = editor_client.delete(detail_url)

        assert listed.status_code == status.HTTP_200_OK, listed.content
        assert retrieved.status_code == status.HTTP_200_OK, retrieved.content
        assert deleted.status_code == status.HTTP_204_NO_CONTENT, deleted.content
        assert not ScheduleTriggerNode.objects.filter(pk=schedule_node.pk).exists()

    def test_superadmin_needs_no_role(self, org_client_as, superadmin, acme, acme_graph):
        response = org_client_as(superadmin, acme).post(
            reverse("scheduletriggernode-list"),
            {"graph": acme_graph.id, "node_name": "Admin schedule"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content
