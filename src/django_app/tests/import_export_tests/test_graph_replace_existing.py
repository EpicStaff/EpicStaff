import json
from unittest import mock

import pytest
from django.urls import reverse

from django_app.settings import SCHEDULE_CHANNEL
from rbac.models import OrganizationUser, Role
from rbac.models.enums import Permission, ResourceType
from rbac.models.role import RolePermission
from tables.exceptions import GraphSaveVersionConflictError
from tables.graph_collab.notifications import GraphEditNotifier
from tables.graph_versioning.services import GraphVersioningService
from tables.import_export.enums import EntityType, NodeType
from tables.import_export.registry import entity_registry
from tables.import_export.services.export_service import ExportService
from tables.models import (
    Graph,
    GraphOrganization,
    GraphVersion,
    PythonCode,
    ScheduleTriggerNode,
    Session,
    StartNode,
    SubGraphNode,
    TelegramTriggerNode,
    WebhookTrigger,
    WebhookTriggerNode,
)
from tables.models.graph_models import GraphNote
from tables.models.label_models import Label
from tables.models.webhook_models import WebhookTriggerAuth, WebhookTriggerAuthKind
from tables.services.secrets import secret_service
from tests.helpers import data_to_json_file
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.fixture(autouse=True)
def soft_delete(request, settings):
    """SOFT_DELETE is on unless a test parametrizes this fixture indirectly."""
    settings.SOFT_DELETE = getattr(request, "param", True)
    return settings.SOFT_DELETE


both_delete_modes = pytest.mark.parametrize(
    "soft_delete", [True, False], ids=["soft", "hard"], indirect=True
)


def _flow(org, name):
    graph = Graph.objects.create(name=name, org=org, metadata={"nodes": [], "edges": []})
    StartNode.objects.create(graph=graph, variables={})
    return graph


def _export(graph):
    return ExportService(entity_registry).export_entities(EntityType.GRAPH, [graph.id])


def _flow_edited_after_export(org, name="My Flow"):
    """A flow plus an export of it, taken before the flow was edited further.

    The export carries description "from file" and a "file note"; the flow now
    holds description "old description" and an "old note".
    """
    graph = _flow(org, name)
    graph.description = "from file"
    graph.save()
    file_note = GraphNote.objects.create(graph=graph, content="file note")
    export_data = _export(graph)
    file_note.delete()
    GraphNote.objects.create(graph=graph, content="old note")
    graph.description = "old description"
    graph.save()
    return graph, export_data


def _import(client, org, export_data, *, replace_existing, preserve_uuids=True, **extra):
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client.post(
        reverse("graphs-import-entity"),
        {
            "file": data_to_json_file(data=export_data, filename="flow.json"),
            "preserve_uuids": preserve_uuids,
            "replace_existing": replace_existing,
            **extra,
        },
        format="multipart",
    )


def _note_contents(graph):
    return list(graph.graph_note_list.values_list("content", flat=True))


def _flow_with_webhook(org, path):
    graph = _flow(org, "Hook Flow")
    trigger = WebhookTrigger.objects.create(path=path, org=org)
    code = PythonCode.objects.create(code="def main(): ...", entrypoint="main", libraries="")
    WebhookTriggerNode.objects.create(
        graph=graph, node_name="wt", webhook_trigger=trigger, python_code=code
    )
    return graph, trigger


def _flow_with_telegram_bots(org, *bots):
    """A flow whose Telegram trigger nodes each hold their own bot key.

    Each bot is (node name, webhook trigger path); bots given the same path share
    one trigger. Returns the flow, triggers by path and bot keys by node name.
    """
    graph = _flow(org, "Bot Flow")
    triggers, bot_keys = {}, {}
    for index, (node_name, path) in enumerate(bots):
        if path not in triggers:
            triggers[path] = WebhookTrigger.objects.create(path=path, org=org)
            WebhookTriggerAuth.objects.create(
                trigger=triggers[path], kind=WebhookTriggerAuthKind.TELEGRAM
            )
        bot_keys[node_name] = secret_service.create(
            text=f"bot-key-{index}", org=org, name=f"bot-key-{index}"
        )
        TelegramTriggerNode.objects.create(
            graph=graph,
            node_name=node_name,
            webhook_trigger=triggers[path],
            telegram_bot_api_key_secret=bot_keys[node_name],
        )
    return graph, triggers, bot_keys


def _telegram_keys_by_trigger(graph):
    return dict(
        graph.telegram_trigger_node_list.values_list(
            "webhook_trigger_id", "telegram_bot_api_key_secret_id"
        )
    )


def _append_invalid_note(export_data):
    """Make the import fail after the replaced flow was already emptied."""
    export_data[EntityType.GRAPH][0]["nodes"].append(
        {"node_type": NodeType.NOTE_NODE, "id": 999999, "metadata": {}}
    )


def _schedule_events(redis_client_mock):
    return [
        json.loads(call.args[1])["data"]
        for call in redis_client_mock.publish.call_args_list
        if call.args[0] == SCHEDULE_CHANNEL
    ]


@pytest.mark.django_db
class TestReplaceInPlace:
    @both_delete_modes
    def test_replace_keeps_the_row_and_takes_the_file_content(self, client_as, admin_acme, acme):
        holder, export_data = _flow_edited_after_export(acme)
        original_uuid = holder.uuid
        session = Session.objects.create(graph=holder, status=Session.SessionStatus.END)
        earlier_version = GraphVersioningService().save_version(holder, name="v1")
        graph_organization_id = GraphOrganization.objects.create(graph=holder).id

        response = _import(client_as(admin_acme), acme, export_data, replace_existing=True)

        assert response.status_code == 200
        holder.refresh_from_db()
        assert holder.uuid == original_uuid
        assert holder.name == "My Flow"
        assert holder.description == "from file"
        assert _note_contents(holder) == ["file note"]
        assert holder.start_node_list.count() == 1
        assert Graph.objects.filter(org=acme).count() == 1
        session.refresh_from_db()
        assert session.graph_id == holder.id
        assert GraphVersion.objects.filter(id=earlier_version.id, graph=holder).exists()
        assert GraphOrganization.objects.get(graph=holder).id == graph_organization_id
        flow_summary = response.json()[EntityType.GRAPH.value]
        assert [item["id"] for item in flow_summary["created"]["items"]] == [holder.id]

    def test_replace_saves_a_backup_version_of_the_old_content(self, client_as, admin_acme, acme):
        holder, export_data = _flow_edited_after_export(acme)

        response = _import(client_as(admin_acme), acme, export_data, replace_existing=True)

        assert response.status_code == 200
        backup = GraphVersion.objects.get(graph=holder)
        assert backup.name == "Before import"
        assert backup.snapshot["description"] == "old description"
        backup_notes = [
            node["content"]
            for node in backup.snapshot["nodes"]
            if node["node_type"] == NodeType.NOTE_NODE
        ]
        assert backup_notes == ["old note"]

    def test_replace_bumps_save_version_so_a_stale_editor_conflicts(
        self, client_as, admin_acme, acme
    ):
        holder, export_data = _flow_edited_after_export(acme)
        editor_save_version = holder.save_version

        response = _import(client_as(admin_acme), acme, export_data, replace_existing=True)

        assert response.status_code == 200
        holder.refresh_from_db()
        assert holder.save_version == editor_save_version + 1
        with pytest.raises(GraphSaveVersionConflictError):
            Graph.increment_version_if_current(pk=holder.pk, expected=editor_save_version)

    def test_replace_takes_the_renamed_flow_name(self, client_as, admin_acme, acme):
        holder = _flow(acme, "My Flow")
        export_data = _export(holder)
        export_data[EntityType.GRAPH][0]["name"] = "Renamed Flow"

        response = _import(client_as(admin_acme), acme, export_data, replace_existing=True)

        assert response.status_code == 200
        holder.refresh_from_db()
        assert holder.name == "Renamed Flow"

    def test_replace_name_taken_by_another_flow_gets_a_suffix(self, client_as, admin_acme, acme):
        holder = _flow(acme, "My Flow")
        _flow(acme, "Taken")
        export_data = _export(holder)
        export_data[EntityType.GRAPH][0]["name"] = "Taken"

        response = _import(client_as(admin_acme), acme, export_data, replace_existing=True)

        assert response.status_code == 200
        holder.refresh_from_db()
        assert holder.name == "Taken #2"

    @both_delete_modes
    def test_parent_subgraph_node_keeps_pointing_at_the_replaced_flow(
        self, client_as, admin_acme, acme
    ):
        subflow = _flow(acme, "Sub")
        parent_node = SubGraphNode.objects.create(
            graph=_flow(acme, "Parent"), subgraph=subflow, node_name="call sub", input_map={}
        )

        response = _import(client_as(admin_acme), acme, _export(subflow), replace_existing=True)

        assert response.status_code == 200
        parent_node.refresh_from_db()
        assert parent_node.subgraph_id == subflow.id

    @both_delete_modes
    def test_replacing_parent_and_subflow_keeps_both_rows(self, client_as, admin_acme, acme):
        subflow = _flow(acme, "Sub")
        parent = _flow(acme, "Parent")
        SubGraphNode.objects.create(
            graph=parent, subgraph=subflow, node_name="call sub", input_map={}
        )
        export_data = _export(parent)
        assert len(export_data[EntityType.GRAPH]) == 2

        response = _import(client_as(admin_acme), acme, export_data, replace_existing=True)

        assert response.status_code == 200
        assert set(Graph.objects.filter(org=acme).values_list("id", flat=True)) == {
            subflow.id,
            parent.id,
        }
        assert list(parent.subgraph_node_list.values_list("subgraph_id", flat=True)) == [
            subflow.id
        ]
        assert GraphVersion.objects.filter(graph__in=[parent, subflow]).count() == 2

    def test_replace_reuses_the_flows_own_webhook_trigger(self, client_as, admin_acme, acme):
        holder, trigger = _flow_with_webhook(acme, "acme-hook")

        response = _import(client_as(admin_acme), acme, _export(holder), replace_existing=True)

        assert response.status_code == 200
        assert list(WebhookTrigger.objects.filter(path="acme-hook")) == [trigger]
        node_triggers = holder.webhook_trigger_node_list.values_list("webhook_trigger_id", flat=True)
        assert list(node_triggers) == [trigger.id]

    def test_failed_replace_rolls_back_the_backup_and_the_wipe(self, client_as, admin_acme, acme):
        holder, export_data = _flow_edited_after_export(acme)
        save_version_before = holder.save_version
        _append_invalid_note(export_data)

        response = _import(client_as(admin_acme), acme, export_data, replace_existing=True)

        assert response.status_code == 400
        holder.refresh_from_db()
        assert holder.description == "old description"
        assert holder.save_version == save_version_before
        assert _note_contents(holder) == ["old note"]
        assert not GraphVersion.objects.filter(graph=holder).exists()

    def test_replace_notifies_open_editors_after_commit(
        self, client_as, admin_acme, acme, django_capture_on_commit_callbacks
    ):
        holder, export_data = _flow_edited_after_export(acme)

        with mock.patch.object(GraphEditNotifier, "notify_graph_saved") as notify:
            with django_capture_on_commit_callbacks(execute=True):
                response = _import(client_as(admin_acme), acme, export_data, replace_existing=True)

        assert response.status_code == 200
        holder.refresh_from_db()
        notify.assert_called_once()
        assert notify.call_args.kwargs["graph_id"] == holder.id
        assert notify.call_args.kwargs["new_save_version"] == holder.save_version
        assert notify.call_args.kwargs["user"] == admin_acme

    def test_failed_replace_notifies_nobody(
        self, client_as, admin_acme, acme, django_capture_on_commit_callbacks
    ):
        holder, export_data = _flow_edited_after_export(acme)
        _append_invalid_note(export_data)

        with mock.patch.object(GraphEditNotifier, "notify_graph_saved") as notify:
            with django_capture_on_commit_callbacks(execute=True):
                response = _import(client_as(admin_acme), acme, export_data, replace_existing=True)

        assert response.status_code == 400
        notify.assert_not_called()

    def test_file_cannot_soft_delete_the_replaced_flow(self, client_as, admin_acme, acme):
        holder, export_data = _flow_edited_after_export(acme)
        export_data[EntityType.GRAPH][0].update(
            {"active": False, "soft_deleted_at": "2026-01-01T00:00:00Z"}
        )

        response = _import(client_as(admin_acme), acme, export_data, replace_existing=True)

        assert response.status_code == 200
        holder.refresh_from_db()
        assert holder.active
        assert holder.soft_deleted_at is None
        assert holder.description == "from file"

    def test_replace_keeps_the_original_author(self, client_as, admin_acme, member_only, acme):
        holder = _flow(acme, "My Flow")
        holder.created_by = member_only
        holder.save()

        response = _import(client_as(admin_acme), acme, _export(holder), replace_existing=True)

        assert response.status_code == 200
        holder.refresh_from_db()
        assert holder.created_by_id == member_only.id


@pytest.mark.django_db
class TestReplaceKeepsTriggerSetup:
    def test_webhook_trigger_auth_survives_the_replace(
        self, client_as, admin_acme, acme, django_capture_on_commit_callbacks
    ):
        holder, trigger = _flow_with_webhook(acme, "acme-hook")
        WebhookTriggerAuth.objects.create(trigger=trigger, kind=WebhookTriggerAuthKind.WEBHOOK)

        with django_capture_on_commit_callbacks(execute=True):
            response = _import(
                client_as(admin_acme), acme, _export(holder), replace_existing=True
            )

        assert response.status_code == 200
        assert WebhookTriggerAuth.objects.filter(
            trigger=trigger, kind=WebhookTriggerAuthKind.WEBHOOK
        ).exists()

    def test_telegram_bot_key_and_auth_survive_the_replace(
        self,
        client_as,
        admin_acme,
        acme,
        mock_telegram_service,
        django_capture_on_commit_callbacks,
    ):
        holder, triggers, bot_keys = _flow_with_telegram_bots(acme, ("Telegram Bot #7", "acme-bot"))
        trigger, bot_key = triggers["acme-bot"], bot_keys["Telegram Bot #7"]

        with django_capture_on_commit_callbacks(execute=True):
            response = _import(
                client_as(admin_acme), acme, _export(holder), replace_existing=True
            )

        assert response.status_code == 200
        node = holder.telegram_trigger_node_list.get()
        # Recreated nodes are renumbered; the key follows the trigger, not the name.
        assert node.node_name != "Telegram Bot #7"
        assert node.webhook_trigger_id == trigger.id
        assert node.telegram_bot_api_key_secret_id == bot_key.id
        registered_nodes = [
            call.kwargs["telegram_trigger_instance"] for call in mock_telegram_service.call_args_list
        ]
        assert any(
            registered.pk == node.pk and registered.telegram_bot_api_key_secret_id == bot_key.id
            for registered in registered_nodes
        )
        assert WebhookTriggerAuth.objects.filter(
            trigger=trigger, kind=WebhookTriggerAuthKind.TELEGRAM
        ).exists()

    def test_each_telegram_bot_keeps_the_key_of_its_own_trigger(
        self, client_as, admin_acme, acme, mock_telegram_service
    ):
        holder, triggers, bot_keys = _flow_with_telegram_bots(
            acme, ("Telegram Bot #1", "bot-one"), ("Telegram Bot #2", "bot-two")
        )
        old_node_ids = set(holder.telegram_trigger_node_list.values_list("id", flat=True))

        response = _import(client_as(admin_acme), acme, _export(holder), replace_existing=True)

        assert response.status_code == 200
        new_node_ids = set(holder.telegram_trigger_node_list.values_list("id", flat=True))
        assert new_node_ids.isdisjoint(old_node_ids)
        assert _telegram_keys_by_trigger(holder) == {
            triggers["bot-one"].id: bot_keys["Telegram Bot #1"].id,
            triggers["bot-two"].id: bot_keys["Telegram Bot #2"].id,
        }

    def test_telegram_bots_sharing_a_trigger_get_no_key(
        self, client_as, admin_acme, acme, mock_telegram_service
    ):
        holder, _, _ = _flow_with_telegram_bots(
            acme, ("Telegram Bot #1", "shared-bot"), ("Telegram Bot #2", "shared-bot")
        )

        response = _import(client_as(admin_acme), acme, _export(holder), replace_existing=True)

        assert response.status_code == 200
        assert list(
            holder.telegram_trigger_node_list.values_list("telegram_bot_api_key_secret", flat=True)
        ) == [None, None]

    def test_key_is_not_handed_to_another_node_of_the_same_trigger(
        self, client_as, admin_acme, acme, mock_telegram_service
    ):
        holder, _, _ = _flow_with_telegram_bots(
            acme, ("Keyed Bot #1", "shared-bot"), ("Unkeyed Bot #2", "shared-bot")
        )
        holder.telegram_trigger_node_list.filter(node_name="Unkeyed Bot #2").update(
            telegram_bot_api_key_secret=None
        )
        export_data = _export(holder)
        flow_data = export_data[EntityType.GRAPH][0]
        flow_data["nodes"] = [
            node for node in flow_data["nodes"] if node.get("node_name") != "Keyed Bot #1"
        ]

        response = _import(client_as(admin_acme), acme, export_data, replace_existing=True)

        assert response.status_code == 200
        node = holder.telegram_trigger_node_list.get()
        assert node.node_name.startswith("Unkeyed Bot")
        assert node.telegram_bot_api_key_secret_id is None

    def test_restoring_the_backup_brings_back_bot_keys_the_replace_dropped(
        self, client_as, admin_acme, acme, mock_telegram_service
    ):
        holder, _, bot_keys = _flow_with_telegram_bots(
            acme, ("Telegram Bot #1", "shared-bot"), ("Telegram Bot #2", "shared-bot")
        )
        response = _import(client_as(admin_acme), acme, _export(holder), replace_existing=True)
        assert response.status_code == 200
        holder.refresh_from_db()

        GraphVersioningService().restore_version(
            GraphVersion.objects.get(graph=holder, name="Before import"),
            expected_save_version=holder.save_version,
        )

        restored_keys = holder.telegram_trigger_node_list.values_list(
            "telegram_bot_api_key_secret", flat=True
        )
        assert sorted(restored_keys) == sorted(key.id for key in bot_keys.values())

    def test_replace_publishes_schedule_changes_after_commit(
        self, client_as, admin_acme, acme, redis_client_mock, django_capture_on_commit_callbacks
    ):
        holder = _flow(acme, "Scheduled Flow")
        old_node = ScheduleTriggerNode.objects.create(graph=holder, node_name="Hourly")
        export_data = _export(holder)

        with django_capture_on_commit_callbacks(execute=True):
            response = _import(client_as(admin_acme), acme, export_data, replace_existing=True)

        assert response.status_code == 200
        new_node = holder.schedule_trigger_node_list.get()
        published = {(event["action"], event["node"]["id"]) for event in _schedule_events(redis_client_mock)}
        assert {("delete", old_node.id), ("create", new_node.id)} <= published

    def test_failed_replace_publishes_no_schedule_change(
        self, client_as, admin_acme, acme, redis_client_mock, django_capture_on_commit_callbacks
    ):
        holder = _flow(acme, "Scheduled Flow")
        ScheduleTriggerNode.objects.create(graph=holder, node_name="Hourly")
        export_data = _export(holder)
        _append_invalid_note(export_data)

        with django_capture_on_commit_callbacks(execute=True):
            response = _import(client_as(admin_acme), acme, export_data, replace_existing=True)

        assert response.status_code == 400
        assert _schedule_events(redis_client_mock) == []
        assert holder.schedule_trigger_node_list.count() == 1


@pytest.mark.django_db
class TestReplaceLabels:
    def _labelled_flow(self, org):
        file_label = Label.objects.create(org=org, name="From File", scope=Label.Scope.FLOW)
        holder = _flow(org, "My Flow")
        holder.labels.add(file_label)
        export_data = _export(holder)
        holder.labels.set([Label.objects.create(org=org, name="Added Later")])
        return holder, export_data

    def test_importing_labels_applies_the_file_labels(self, client_as, admin_acme, acme):
        holder, export_data = self._labelled_flow(acme)

        response = _import(
            client_as(admin_acme), acme, export_data, replace_existing=True, import_labels=True
        )

        assert response.status_code == 200
        assert list(holder.labels.values_list("name", flat=True)) == ["From File"]

    def test_not_importing_labels_keeps_the_flows_labels(self, client_as, admin_acme, acme):
        holder, export_data = self._labelled_flow(acme)

        response = _import(
            client_as(admin_acme), acme, export_data, replace_existing=True, import_labels=False
        )

        assert response.status_code == 200
        assert list(holder.labels.values_list("name", flat=True)) == ["Added Later"]


@pytest.mark.django_db
class TestWithoutReplace:
    def test_creates_numbered_copy_with_fresh_uuid(self, client_as, admin_acme, acme):
        old = _flow(acme, "My Flow")
        original_uuid = old.uuid

        response = _import(client_as(admin_acme), acme, _export(old), replace_existing=False)

        assert response.status_code == 200
        old.refresh_from_db()
        assert old.active
        assert old.uuid == original_uuid
        copy = Graph.objects.get(org=acme, name="My Flow #2")
        assert copy.uuid != original_uuid
        assert copy.created_by_id == admin_acme.id
        assert not GraphVersion.objects.filter(graph=old).exists()

    def test_soft_deleted_holder_gives_its_uuid_to_the_import(self, client_as, admin_acme, acme):
        live = _flow(acme, "Live Flow")
        holder = _flow(acme, "Deleted Flow")
        holder.delete()
        export_data = _export(live)
        export_data[EntityType.GRAPH][0]["uuid"] = str(holder.uuid)

        response = _import(client_as(admin_acme), acme, export_data, replace_existing=False)

        assert response.status_code == 200
        live.refresh_from_db()
        assert live.active
        rotated_holder = Graph.all_objects.get(id=holder.id)
        assert not rotated_holder.active
        assert rotated_holder.uuid != holder.uuid
        imported = Graph.objects.get(uuid=holder.uuid)
        assert imported.id not in (live.id, holder.id)
        assert imported.name == "Live Flow #2"

    def test_file_cannot_create_an_already_deleted_flow(self, client_as, admin_acme, acme):
        export_data = _export(_flow(acme, "My Flow"))
        export_data[EntityType.GRAPH][0].update(
            {"active": False, "soft_deleted_at": "2026-01-01T00:00:00Z"}
        )

        response = _import(
            client_as(admin_acme), acme, export_data, replace_existing=False, preserve_uuids=False
        )

        assert response.status_code == 200
        copy = Graph.all_objects.get(org=acme, name="My Flow #2")
        assert copy.active
        assert copy.soft_deleted_at is None


@pytest.mark.django_db
class TestReplaceExistingCrossOrg:
    @pytest.mark.parametrize("replace_existing", [True, False])
    def test_uuid_of_other_org_graph_is_left_alone(
        self, client_as, admin_acme, acme, beta, replace_existing
    ):
        beta_graph = _flow(beta, "Beta Flow")
        beta_uuid = beta_graph.uuid
        export_data = _export(_flow(acme, "Acme Flow"))
        export_data[EntityType.GRAPH][0]["uuid"] = str(beta_uuid)

        response = _import(
            client_as(admin_acme), acme, export_data, replace_existing=replace_existing
        )

        assert response.status_code == 200
        beta_graph = Graph.all_objects.get(id=beta_graph.id)
        assert beta_graph.active
        assert beta_graph.uuid == beta_uuid
        assert beta_graph.name == "Beta Flow"
        assert not GraphVersion.objects.filter(graph=beta_graph).exists()
        imported = Graph.objects.filter(org=acme).exclude(name="Acme Flow").get()
        assert imported.uuid != beta_uuid

    def test_soft_deleted_other_org_graph_keeps_its_uuid(self, client_as, admin_acme, acme, beta):
        beta_graph = _flow(beta, "Beta Flow")
        beta_graph.delete()
        beta_uuid = beta_graph.uuid
        export_data = _export(_flow(acme, "Acme Flow"))
        export_data[EntityType.GRAPH][0]["uuid"] = str(beta_uuid)

        response = _import(client_as(admin_acme), acme, export_data, replace_existing=True)

        assert response.status_code == 200
        assert Graph.all_objects.get(id=beta_graph.id).uuid == beta_uuid
        assert not Graph.objects.filter(org=acme, uuid=beta_uuid).exists()


@pytest.fixture
def flows_creator_without_update(db, django_user_model, acme):
    role = Role.objects.create(name="Flow Creator", org=acme, is_built_in=False)
    RolePermission.objects.create(
        role=role,
        resource_type=ResourceType.FLOWS,
        permissions=int(Permission.CREATE | Permission.READ | Permission.LIST),
    )
    user = django_user_model.objects.create_user(
        email="flow-creator@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=role)
    return user


@pytest.mark.django_db
class TestReplaceExistingPermission:
    def test_role_without_flows_update_cannot_replace(
        self, client_as, flows_creator_without_update, acme
    ):
        holder, export_data = _flow_edited_after_export(acme)
        save_version_before = holder.save_version

        response = _import(
            client_as(flows_creator_without_update), acme, export_data, replace_existing=True
        )

        assert response.status_code == 403
        holder.refresh_from_db()
        assert holder.description == "old description"
        assert holder.save_version == save_version_before
        assert _note_contents(holder) == ["old note"]
        assert not GraphVersion.objects.filter(graph=holder).exists()
        assert Graph.objects.filter(org=acme).count() == 1

    def test_role_without_flows_update_can_import_without_replace(
        self, client_as, flows_creator_without_update, acme
    ):
        old = _flow(acme, "My Flow")

        response = _import(
            client_as(flows_creator_without_update), acme, _export(old), replace_existing=False
        )

        assert response.status_code == 200
        assert Graph.objects.filter(org=acme).count() == 2

    def test_member_can_replace(self, client_as, member_only, acme):
        holder, export_data = _flow_edited_after_export(acme)

        response = _import(client_as(member_only), acme, export_data, replace_existing=True)

        assert response.status_code == 200
        holder.refresh_from_db()
        assert holder.description == "from file"
        assert Graph.objects.filter(org=acme).count() == 1

    def test_member_without_replace_cannot_take_an_active_flows_uuid(
        self, client_as, member_only, acme
    ):
        victim = _flow(acme, "Victim Flow")
        victim_uuid = victim.uuid
        export_data = _export(_flow(acme, "Attacker Flow"))
        export_data[EntityType.GRAPH][0]["uuid"] = str(victim_uuid)

        response = _import(client_as(member_only), acme, export_data, replace_existing=False)

        assert response.status_code == 200
        victim.refresh_from_db()
        assert victim.uuid == victim_uuid
        assert victim.name == "Victim Flow"
        assert Graph.objects.get(uuid=victim_uuid).id == victim.id
