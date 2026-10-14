"""The trigger node service: who may write trigger nodes, and whether a source holds one."""

import pytest
from django.utils import timezone

from tables.import_export.enums import EntityType, NodeType
from tables.models import Graph, PythonCode, WebhookTrigger
from tables.models.graph_models import ScheduleTriggerNode, TelegramTriggerNode, WebhookTriggerNode
from rbac.access.effective import EffectivePermissions
from rbac.models import OrganizationUser, Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from tables.exceptions import (
    FlowWithTriggerNodesRequiresRunPermissionError,
    TriggerNodesRequireRunPermissionError,
)
from tables.services.trigger_nodes import (
    TRIGGER_NODE_TYPES,
    TriggerNodeAccess,
    TriggerNodeInspector,
)
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


def test_trigger_node_types_derive_from_the_registry():
    assert TRIGGER_NODE_TYPES == {
        NodeType.WEBHOOK_TRIGGER_NODE,
        NodeType.TELEGRAM_TRIGGER_NODE,
        NodeType.SCHEDULE_TRIGGER_NODE,
    }


@pytest.mark.django_db
class TestGraphHasTriggerNodes:
    @pytest.mark.parametrize("make_trigger", ["webhook", "telegram", "schedule"])
    def test_each_trigger_type_counts(self, acme, make_trigger):
        graph = Graph.objects.create(name=f"flow-{make_trigger}", org=acme)
        if make_trigger == "webhook":
            WebhookTriggerNode.objects.create(
                graph=graph, node_name="w", python_code=PythonCode.objects.create(code="x")
            )
        elif make_trigger == "telegram":
            TelegramTriggerNode.objects.create(graph=graph, node_name="t")
        else:
            ScheduleTriggerNode.objects.create(graph=graph, node_name="s")

        assert TriggerNodeInspector.has_any_in_graph(graph) is True

    def test_flow_without_triggers(self, acme):
        assert TriggerNodeInspector.has_any_in_graph(Graph.objects.create(name="plain", org=acme)) is False

    def test_soft_deleted_trigger_does_not_count(self, acme):
        graph = Graph.objects.create(name="deleted-trigger", org=acme)
        node = ScheduleTriggerNode.objects.create(graph=graph, node_name="gone")
        ScheduleTriggerNode.all_objects.filter(pk=node.pk).update(
            is_soft_deleted=True, soft_deleted_at=timezone.now()
        )

        assert TriggerNodeInspector.has_any_in_graph(graph) is False

    def test_uses_prefetched_node_lists(self, acme, django_assert_num_queries):
        graph = Graph.objects.create(name="prefetched", org=acme)
        ScheduleTriggerNode.objects.create(graph=graph, node_name="s")
        prefetched = Graph.objects.prefetch_related(
            "webhook_trigger_node_list", "telegram_trigger_node_list", "schedule_trigger_node_list"
        ).get(pk=graph.pk)

        with django_assert_num_queries(0):
            assert TriggerNodeInspector.has_any_in_graph(prefetched) is True


def _flow_entry(*node_types):
    return {"name": "flow", "nodes": [{"node_type": node_type} for node_type in node_types]}


class TestNodeEntries:
    def test_a_trigger_among_the_entries(self):
        entries = [{"node_type": "PythonNode"}, {"node_type": "WebhookTriggerNode"}]

        assert TriggerNodeInspector.has_any_in_node_entries(entries)

    def test_without_triggers(self):
        assert not TriggerNodeInspector.has_any_in_node_entries([{"node_type": "PythonNode"}])
        assert not TriggerNodeInspector.has_any_in_node_entries([])


class TestFlowEntryHasTriggerNodes:
    def test_snapshot_or_exported_flow_with_a_trigger(self):
        assert TriggerNodeInspector.has_any_in_flow_entry(_flow_entry("PythonNode", "ScheduleTriggerNode"))

    def test_without_triggers(self):
        assert not TriggerNodeInspector.has_any_in_flow_entry(_flow_entry("PythonNode", "NoteNode"))
        assert not TriggerNodeInspector.has_any_in_flow_entry({})


class TestExportHasTriggerNodes:
    def test_trigger_in_any_flow_of_a_full_export(self):
        export_data = {
            EntityType.GRAPH: [_flow_entry("PythonNode"), _flow_entry("TelegramTriggerNode")]
        }

        assert TriggerNodeInspector.has_any_in_export(export_data)

    def test_trigger_in_a_partial_export(self):
        assert TriggerNodeInspector.has_any_in_export({EntityType.WEBHOOK_TRIGGER_NODE: [{"id": 1}]})

    def test_without_triggers(self):
        assert not TriggerNodeInspector.has_any_in_export(
            {EntityType.GRAPH: [_flow_entry("PythonNode")], EntityType.PYTHON_NODE: [{"id": 1}]}
        )
        assert not TriggerNodeInspector.has_any_in_export({EntityType.WEBHOOK_TRIGGER_NODE: []})


@pytest.mark.django_db
class TestAttachedToWebhookTrigger:
    def test_webhook_or_telegram_node_attached(self, acme):
        graph = Graph.objects.create(name="attached", org=acme)
        webhook_trigger = WebhookTrigger.objects.create(path="insp-webhook", org=acme)
        telegram_trigger = WebhookTrigger.objects.create(path="insp-telegram", org=acme)
        WebhookTriggerNode.objects.create(
            graph=graph,
            node_name="w",
            webhook_trigger=webhook_trigger,
            python_code=PythonCode.objects.create(code="x"),
        )
        TelegramTriggerNode.objects.create(
            graph=graph, node_name="t", webhook_trigger=telegram_trigger
        )

        assert TriggerNodeInspector.has_any_attached_to_webhook_trigger(webhook_trigger)
        assert TriggerNodeInspector.has_any_attached_to_webhook_trigger(telegram_trigger)

    def test_no_live_node_attached(self, acme):
        graph = Graph.objects.create(name="detached", org=acme)
        trigger = WebhookTrigger.objects.create(path="insp-free", org=acme)
        node = WebhookTriggerNode.objects.create(
            graph=graph,
            node_name="w",
            webhook_trigger=trigger,
            python_code=PythonCode.objects.create(code="x"),
        )
        WebhookTriggerNode.all_objects.filter(pk=node.pk).update(
            is_soft_deleted=True, soft_deleted_at=timezone.now()
        )

        assert not TriggerNodeInspector.has_any_attached_to_webhook_trigger(trigger)


# ── TriggerNodeAccess ────────────────────────────────────────────────────────


def _effective(flows_permissions):
    return EffectivePermissions(
        is_superadmin=False, role=None, by_resource={"flows": int(flows_permissions)}
    )


class TestAssertMayRecreate:
    def test_without_run_raises_the_flow_error(self):
        with pytest.raises(FlowWithTriggerNodesRequiresRunPermissionError):
            TriggerNodeAccess().assert_may_recreate(
                _effective(Permission.CREATE | Permission.READ | Permission.UPDATE)
            )

    def test_with_run_or_as_superadmin_passes(self):
        TriggerNodeAccess().assert_may_recreate(_effective(Permission.READ | Permission.RUN))
        TriggerNodeAccess().assert_may_recreate(
            EffectivePermissions(is_superadmin=True, role=None, by_resource={})
        )


@pytest.mark.django_db
class TestAssertMayWriteAndRecreateByUser:
    @pytest.fixture
    def member(self, django_user_model, acme):
        def make(flows_permissions, name):
            role = Role.objects.create(name=name, org=acme, is_built_in=False)
            RolePermission.objects.create(
                role=role, resource_type=ResourceType.FLOWS, permissions=int(flows_permissions)
            )
            user = django_user_model.objects.create_user(
                email=f"{name}@example.com", password="StrongPass123!"
            )
            OrganizationUser.objects.create(user=user, org=acme, role=role)
            return user

        return make

    def test_without_run_each_raises_its_own_error(self, member, acme):
        user = member(Permission.READ | Permission.UPDATE, "access-no-run")
        access = TriggerNodeAccess()

        with pytest.raises(TriggerNodesRequireRunPermissionError):
            access.assert_may_write(user, acme.id)
        with pytest.raises(FlowWithTriggerNodesRequiresRunPermissionError):
            access.assert_user_may_recreate(user, acme.id)

    def test_with_run_both_pass(self, member, acme):
        user = member(Permission.READ | Permission.RUN, "access-run")
        access = TriggerNodeAccess()

        access.assert_may_write(user, acme.id)
        access.assert_user_may_recreate(user, acme.id)
