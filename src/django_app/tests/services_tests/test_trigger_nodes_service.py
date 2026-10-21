"""The trigger node service: who may write trigger nodes, and whether a source holds one."""

import pytest
from django.utils import timezone

from rbac.access.effective import EffectivePermissions
from rbac.exceptions import OrgMembershipRequiredError
from rbac.models.enums import Permission, ResourceType
from tables.exceptions import (
    FlowWithTriggerNodesRequiresUsePermissionError,
    TriggerNodesRequireUsePermissionError,
)
from tables.import_export.enums import EntityType
from tables.models import Graph, PythonCode, WebhookTrigger
from tables.models.graph_models import ScheduleTriggerNode, TelegramTriggerNode, WebhookTriggerNode
from tables.services.trigger_nodes import TriggerNodeAccess, TriggerNodeInspector
from tests.custom_role_fixtures import *  # noqa: F401,F403
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


def _webhook_node(graph, trigger=None):
    return WebhookTriggerNode.objects.create(
        graph=graph,
        node_name="w",
        webhook_trigger=trigger,
        python_code=PythonCode.objects.create(code="x"),
    )


def _telegram_node(graph, trigger=None):
    return TelegramTriggerNode.objects.create(graph=graph, node_name="t", webhook_trigger=trigger)


def _schedule_node(graph):
    return ScheduleTriggerNode.objects.create(graph=graph, node_name="s")


def _soft_delete(model, node):
    model.all_objects.filter(pk=node.pk).update(is_soft_deleted=True, soft_deleted_at=timezone.now())


# ── a stored flow ────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestGraphHasTriggerNodes:
    @pytest.mark.parametrize(
        "add_trigger_node",
        [_webhook_node, _telegram_node, _schedule_node],
        ids=["webhook", "telegram", "schedule"],
    )
    def test_each_trigger_type_counts(self, acme, add_trigger_node):
        graph = Graph.objects.create(name="flow", org=acme)
        add_trigger_node(graph)

        assert TriggerNodeInspector.has_any_in_graph(graph) is True

    def test_flow_without_triggers(self, acme):
        assert TriggerNodeInspector.has_any_in_graph(Graph.objects.create(name="plain", org=acme)) is False

    def test_soft_deleted_trigger_does_not_count(self, acme):
        graph = Graph.objects.create(name="deleted-trigger", org=acme)
        _soft_delete(ScheduleTriggerNode, _schedule_node(graph))

        assert TriggerNodeInspector.has_any_in_graph(graph) is False

    def test_uses_prefetched_node_lists(self, acme, django_assert_num_queries):
        graph = Graph.objects.create(name="prefetched", org=acme)
        _schedule_node(graph)
        prefetched = Graph.objects.prefetch_related(
            "webhook_trigger_node_list", "telegram_trigger_node_list", "schedule_trigger_node_list"
        ).get(pk=graph.pk)

        with django_assert_num_queries(0):
            assert TriggerNodeInspector.has_any_in_graph(prefetched) is True


# ── exported node entries, flows, snapshots and import files ─────────────────


@pytest.mark.parametrize(
    ("node_types", "expected"),
    [
        (["PythonNode", "WebhookTriggerNode"], True),
        (["TelegramTriggerNode"], True),
        (["ScheduleTriggerNode"], True),
        (["PythonNode", "NoteNode", "StartNode"], False),
        ([], False),
    ],
)
def test_node_entries(node_types, expected):
    entries = [{"node_type": node_type} for node_type in node_types]

    assert TriggerNodeInspector.has_any_in_node_entries(entries) is expected


def _flow_entry(*node_types):
    return {"name": "flow", "nodes": [{"node_type": node_type} for node_type in node_types]}


@pytest.mark.parametrize(
    ("flow_entry", "expected"),
    [
        (_flow_entry("PythonNode", "ScheduleTriggerNode"), True),
        (_flow_entry("PythonNode", "NoteNode"), False),
        ({}, False),
    ],
    ids=["with-a-trigger", "without-triggers", "no-nodes-key"],
)
def test_flow_entry_or_snapshot(flow_entry, expected):
    assert TriggerNodeInspector.has_any_in_flow_entry(flow_entry) is expected


@pytest.mark.parametrize(
    ("export_data", "expected"),
    [
        ({EntityType.GRAPH: [_flow_entry("PythonNode"), _flow_entry("TelegramTriggerNode")]}, True),
        ({EntityType.WEBHOOK_TRIGGER_NODE: [{"id": 1}]}, True),
        ({EntityType.GRAPH: [_flow_entry("PythonNode")], EntityType.PYTHON_NODE: [{"id": 1}]}, False),
        ({EntityType.WEBHOOK_TRIGGER_NODE: []}, False),
        ({}, False),
    ],
    ids=["trigger-in-a-flow", "loose-trigger", "without-triggers", "empty-trigger-list", "empty"],
)
def test_import_file(export_data, expected):
    assert TriggerNodeInspector.has_any_in_export(export_data) is expected


# ── a stored webhook trigger ─────────────────────────────────────────────────


@pytest.mark.django_db
class TestAttachedToWebhookTrigger:
    def test_webhook_or_telegram_node_attached(self, acme):
        graph = Graph.objects.create(name="attached", org=acme)
        webhook_trigger = WebhookTrigger.objects.create(path="insp-webhook", org=acme)
        telegram_trigger = WebhookTrigger.objects.create(path="insp-telegram", org=acme)
        _webhook_node(graph, webhook_trigger)
        _telegram_node(graph, telegram_trigger)

        assert TriggerNodeInspector.has_any_attached_to_webhook_trigger(webhook_trigger)
        assert TriggerNodeInspector.has_any_attached_to_webhook_trigger(telegram_trigger)

    def test_no_live_node_attached(self, acme):
        graph = Graph.objects.create(name="detached", org=acme)
        trigger = WebhookTrigger.objects.create(path="insp-free", org=acme)
        _soft_delete(WebhookTriggerNode, _webhook_node(graph, trigger))

        assert not TriggerNodeInspector.has_any_attached_to_webhook_trigger(trigger)


@pytest.mark.django_db
class TestGraphsAttachedToWebhookTrigger:
    def test_each_flow_once_whatever_its_trigger_nodes(self, acme):
        trigger = WebhookTrigger.objects.create(path="graphs-attached", org=acme)
        both = Graph.objects.create(name="both kinds", org=acme)
        _webhook_node(both, trigger)
        _webhook_node(both, trigger)
        _telegram_node(both, trigger)
        telegram_only = Graph.objects.create(name="telegram only", org=acme)
        _telegram_node(telegram_only, trigger)

        graphs = TriggerNodeInspector.graphs_attached_to_webhook_trigger(trigger)

        assert sorted(graphs.values_list("id", flat=True)) == sorted([both.id, telegram_only.id])
        assert graphs.count() == 2

    def test_only_flows_on_this_trigger(self, acme):
        trigger = WebhookTrigger.objects.create(path="graphs-mine", org=acme)
        other_trigger = WebhookTrigger.objects.create(path="graphs-other", org=acme)
        _webhook_node(Graph.objects.create(name="other trigger", org=acme), other_trigger)
        Graph.objects.create(name="no triggers", org=acme)
        _schedule_node(Graph.objects.create(name="schedule", org=acme))

        assert not TriggerNodeInspector.graphs_attached_to_webhook_trigger(trigger).exists()

    def test_soft_deleted_nodes_and_flows_do_not_count(self, acme):
        trigger = WebhookTrigger.objects.create(path="graphs-soft-deleted", org=acme)
        _soft_delete(
            WebhookTriggerNode,
            _webhook_node(Graph.objects.create(name="node deleted", org=acme), trigger),
        )
        deleted_graph = Graph.objects.create(name="graph deleted", org=acme)
        _telegram_node(deleted_graph, trigger)
        _soft_delete(Graph, deleted_graph)

        assert not TriggerNodeInspector.graphs_attached_to_webhook_trigger(trigger).exists()

    def test_only_flows_of_the_triggers_org(self, acme, beta):
        trigger = WebhookTrigger.objects.create(path="graphs-org", org=acme)
        _webhook_node(Graph.objects.create(name="beta flow", org=beta), trigger)

        assert not TriggerNodeInspector.graphs_attached_to_webhook_trigger(trigger).exists()

    def test_one_query(self, acme, django_assert_num_queries):
        trigger = WebhookTrigger.objects.create(path="graphs-one-query", org=acme)
        for index in range(3):
            graph = Graph.objects.create(name=f"flow {index}", org=acme)
            _webhook_node(graph, trigger)
            _telegram_node(graph, trigger)

        with django_assert_num_queries(1):
            names = list(
                TriggerNodeInspector.graphs_attached_to_webhook_trigger(trigger).values_list(
                    "name", flat=True
                )
            )

        assert sorted(names) == ["flow 0", "flow 1", "flow 2"]


# ── TriggerNodeAccess ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("effective_permissions", "refused"),
    [
        pytest.param(
            EffectivePermissions(
                is_superadmin=False,
                role=None,
                by_resource={"flows": int(Permission.CREATE | Permission.READ | Permission.UPDATE)},
            ),
            True,
            id="editor-without-use",
        ),
        pytest.param(
            EffectivePermissions(
                is_superadmin=False,
                role=None,
                by_resource={"flows": 0, "webhooks": int(Permission.USE)},
            ),
            True,
            id="use-on-another-resource",
        ),
        pytest.param(
            EffectivePermissions(
                is_superadmin=False,
                role=None,
                by_resource={"flows": int(Permission.READ | Permission.USE)},
            ),
            False,
            id="with-use",
        ),
        pytest.param(
            EffectivePermissions(is_superadmin=True, role=None, by_resource={}),
            False,
            id="superadmin",
        ),
    ],
)
def test_assert_may_recreate(effective_permissions, refused):
    if refused:
        with pytest.raises(FlowWithTriggerNodesRequiresUsePermissionError):
            TriggerNodeAccess().assert_may_recreate(effective_permissions)
    else:
        TriggerNodeAccess().assert_may_recreate(effective_permissions)


@pytest.mark.django_db
class TestAssertMayWriteAndRecreateByUser:
    def test_without_use_each_raises_its_own_error(self, custom_role_member, acme):
        user = custom_role_member(
            acme, {ResourceType.FLOWS: Permission.READ | Permission.UPDATE}, "access-no-use"
        )
        access = TriggerNodeAccess()

        with pytest.raises(TriggerNodesRequireUsePermissionError):
            access.assert_may_write(user, acme.id)
        with pytest.raises(FlowWithTriggerNodesRequiresUsePermissionError):
            access.assert_user_may_recreate(user, acme.id)

    def test_with_use_both_pass(self, custom_role_member, acme):
        user = custom_role_member(
            acme, {ResourceType.FLOWS: Permission.READ | Permission.USE}, "access-use"
        )
        access = TriggerNodeAccess()

        access.assert_may_write(user, acme.id)
        access.assert_user_may_recreate(user, acme.id)

    def test_superadmin_passes_both(self, superadmin, acme):
        access = TriggerNodeAccess()

        access.assert_may_write(superadmin, acme.id)
        access.assert_user_may_recreate(superadmin, acme.id)

    def test_a_runner_of_another_org_is_not_a_member(self, custom_role_member, acme, beta):
        user = custom_role_member(
            beta, {ResourceType.FLOWS: Permission.READ | Permission.USE}, "beta-runner"
        )

        with pytest.raises(OrgMembershipRequiredError):
            TriggerNodeAccess().assert_may_write(user, acme.id)
