"""SoftDeleteFields: the `active` flag and its managers. `objects` (default)
returns active rows, `deleted_objects` binned rows, and `all_objects` (the base
manager) every row."""

import json
from unittest.mock import patch

import pytest
from django.apps import apps
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from tables.models import Graph, ScheduleTriggerNode, SubGraphNode, TaskNode
from tables.models.base_models import ActiveManager, DeletedManager, SoftDeleteFields
from tables.services.soft_delete import DeleteService


def _soft_delete_models():
    return [model for model in apps.get_models() if issubclass(model, SoftDeleteFields)]


@pytest.mark.parametrize("model", _soft_delete_models(), ids=lambda model: model._meta.label)
def test_every_soft_delete_model_has_the_three_managers(model):
    assert model._default_manager.name == "objects"
    assert isinstance(model._default_manager, ActiveManager)
    assert isinstance(model.deleted_objects, DeletedManager)
    assert type(model.all_objects) is models.Manager
    assert model._base_manager.name == "all_objects"
    assert not isinstance(model._base_manager, (ActiveManager, DeletedManager))
    assert {field.name for field in model._meta.get_fields()} >= {"active", "soft_deleted_at"}
    assert "is_soft_deleted" not in {field.name for field in model._meta.get_fields()}


@pytest.mark.django_db
class TestManagers:
    def test_binned_row_is_only_in_deleted_objects_and_all_objects(self, graph):
        DeleteService.delete(graph)

        assert not Graph.objects.filter(pk=graph.pk).exists()
        assert list(Graph.deleted_objects.filter(pk=graph.pk)) == [graph]
        assert Graph.all_objects.filter(pk=graph.pk, active=False).exists()

    def test_active_row_is_not_in_deleted_objects(self, graph):
        assert Graph.objects.filter(pk=graph.pk).exists()
        assert not Graph.deleted_objects.filter(pk=graph.pk).exists()

    def test_reverse_accessor_hides_binned_rows(self, graph):
        task_node = TaskNode.objects.create(graph=graph, node_name="t")
        TaskNode.objects.filter(pk=task_node.pk).update(
            active=False, soft_deleted_at=timezone.now()
        )

        assert not graph.task_node_list.exists()
        assert list(graph.task_node_list(manager="all_objects").all()) == [task_node]

    def test_forward_fk_reaches_a_binned_parent_through_the_base_manager(self, graph):
        task_node = TaskNode.objects.create(graph=graph, node_name="t")
        DeleteService.delete(graph)

        binned_task_node = TaskNode.all_objects.get(pk=task_node.pk)

        assert binned_task_node.active is False
        assert binned_task_node.graph == graph

    def test_new_rows_are_active_through_the_db_default(self, graph):
        assert Graph.objects.filter(pk=graph.pk).values_list("active", flat=True).get() is True


@pytest.mark.django_db
class TestScheduleSignalCombinesBothFlags:
    """`ScheduleTriggerNode.is_active` (schedule on/off) and `active` (not binned)
    are separate fields; the Manager must only run a schedule that is both."""

    @staticmethod
    def _published_is_active(mock_redis_service) -> bool:
        channel_and_message = mock_redis_service.return_value.redis_client.publish.call_args.args
        return json.loads(channel_and_message[1])["data"]["node"]["is_active"]

    def test_live_node_with_schedule_on_publishes_true(self, graph, django_capture_on_commit_callbacks):
        with (
            patch("tables.signals.schedule_signals.RedisService") as mock_redis_service,
            django_capture_on_commit_callbacks(execute=True),
        ):
            ScheduleTriggerNode.objects.create(graph=graph, node_name="cron", is_active=True)

        assert self._published_is_active(mock_redis_service) is True

    def test_binned_node_publishes_false_even_with_schedule_on(self, graph, django_capture_on_commit_callbacks):
        node = ScheduleTriggerNode.objects.create(graph=graph, node_name="cron", is_active=True)
        node.active = False
        node.soft_deleted_at = timezone.now()

        with (
            patch("tables.signals.schedule_signals.RedisService") as mock_redis_service,
            django_capture_on_commit_callbacks(execute=True),
        ):
            node.save(update_fields=["active", "soft_deleted_at"])

        assert ScheduleTriggerNode.all_objects.get(pk=node.pk).is_active is True
        assert self._published_is_active(mock_redis_service) is False


@pytest.mark.django_db
class TestConstraints:
    def test_inactive_row_needs_a_deleted_at(self, graph):
        with pytest.raises(IntegrityError), transaction.atomic():
            Graph.objects.filter(pk=graph.pk).update(active=False)

    def test_active_row_must_not_have_a_deleted_at(self, graph):
        with pytest.raises(IntegrityError), transaction.atomic():
            Graph.objects.filter(pk=graph.pk).update(soft_deleted_at=timezone.now())

    def test_a_binned_flow_frees_its_name(self, graph, default_org):
        DeleteService.delete(graph)

        Graph.objects.create(org=default_org, name=graph.name)

        assert Graph.all_objects.filter(org=default_org, name=graph.name).count() == 2

    def test_two_active_flows_cannot_share_a_name(self, graph, default_org):
        with pytest.raises(IntegrityError), transaction.atomic():
            Graph.objects.create(org=default_org, name=graph.name)


@pytest.mark.django_db
class TestSubflowQuery:
    """`GraphManager.get_transitive_subflows` is raw SQL; it must use the new column."""

    def test_transitive_subflows_skip_binned_nodes_and_flows(self, graph, default_org):
        live_subflow = Graph.objects.create(org=default_org, name="Live sub")
        binned_subflow = Graph.objects.create(org=default_org, name="Binned sub")
        unlinked_subflow = Graph.objects.create(org=default_org, name="Unlinked sub")
        SubGraphNode.objects.create(graph=graph, node_name="a", subgraph=live_subflow)
        SubGraphNode.objects.create(graph=graph, node_name="b", subgraph=binned_subflow)
        binned_node = SubGraphNode.objects.create(graph=graph, node_name="c", subgraph=unlinked_subflow)
        SubGraphNode.objects.filter(pk=binned_node.pk).update(
            active=False, soft_deleted_at=timezone.now()
        )
        DeleteService.delete(binned_subflow)

        assert list(Graph.objects.get_transitive_subflows(graph.id)) == [live_subflow]
