"""RestoreService: one recycle-bin batch comes back, with a "#N" rename when the
name is taken, and nothing deleted outside that batch comes with it."""

import pytest

from rbac.models import Organization
from tables.exceptions import NotInRecycleBinError
from tables.models import Edge, Graph, PythonCode, Secret, SourceCollection, TaskNode
from tables.models.graph_models import ScheduleTriggerNode, TelegramTriggerNode
from tables.models.python_models import PythonCodeTool
from tables.services.recycle_bin.registry import bin_resource_for
from tables.services.recycle_bin.restore_service import RestoreService
from tables.services.secrets import secret_encryption
from tables.services.soft_delete import DeleteService
from tables.models.webhook_models import WebhookTrigger, WebhookTriggerAuth, WebhookTriggerAuthKind
from tables.services.telegram_trigger_service import TelegramTriggerService
from tests.helpers import run_concurrently


def _binned(model, pk):
    return model.all_objects.get(pk=pk)


def _tool(name: str, *, org, built_in: bool = False) -> PythonCodeTool:
    code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main", libraries="", global_kwargs={})
    return PythonCodeTool.objects.create(
        name=name, description="", variables=[], python_code=code, built_in=built_in, org=org
    )


@pytest.mark.django_db
class TestRestoreBringsBackOneBatch:
    def test_restore_brings_back_the_root_and_its_batch(self, graph):
        task_node = TaskNode.objects.create(graph=graph, node_name="task")
        edge = Edge.objects.create(graph=graph)
        graph.delete()

        result = RestoreService.restore(_binned(Graph, graph.pk))

        assert result.object.pk == graph.pk
        assert result.renamed_from is None
        for model, pk in ((Graph, graph.pk), (TaskNode, task_node.pk), (Edge, edge.pk)):
            row = _binned(model, pk)
            assert (row.active, row.soft_deleted_at, row.soft_delete_batch) == (True, None, None), model

    def test_restore_leaves_rows_binned_earlier_on_their_own(self, graph):
        early_node = TaskNode.objects.create(graph=graph, node_name="early")
        DeleteService.delete(early_node)
        graph.delete()

        RestoreService.restore(_binned(Graph, graph.pk))

        assert TaskNode.deleted_objects.filter(pk=early_node.pk).exists()

    def test_restore_refuses_a_live_row(self, graph):
        with pytest.raises(NotInRecycleBinError):
            RestoreService.restore(graph)

    def test_restore_refuses_a_row_binned_without_a_batch(self, graph):
        # Rows binned before batches existed would match every legacy row.
        graph.delete()
        Graph.all_objects.filter(pk=graph.pk).update(soft_delete_batch=None)

        with pytest.raises(NotInRecycleBinError):
            RestoreService.restore(_binned(Graph, graph.pk))


@pytest.mark.django_db
class TestRestoreRenamesWhenTheNameIsTaken:
    def test_flow_gets_the_next_free_number(self, graph):
        name = graph.name
        graph.delete()
        Graph.objects.create(org=graph.org, name=name)

        result = RestoreService.restore(_binned(Graph, graph.pk))

        assert result.renamed_from == name
        assert result.object.name == f"{name} #2"

    def test_collection_uses_the_hash_pattern_not_its_own_parenthesis_rename(self, default_org):
        collection = SourceCollection.objects.create(org=default_org, collection_name="KB")
        collection.delete()
        SourceCollection.objects.create(org=default_org, collection_name="KB")

        result = RestoreService.restore(_binned(SourceCollection, collection.pk))

        assert result.renamed_from == "KB"
        assert _binned(SourceCollection, collection.pk).collection_name == "KB #2"

    def test_python_tool_treats_built_in_names_as_taken(self, default_org):
        _tool("Fetch", org=None, built_in=True)
        org_tool = _tool("Fetch", org=default_org)
        org_tool.delete()

        result = RestoreService.restore(_binned(PythonCodeTool, org_tool.pk))

        assert result.object.name == "Fetch #2"

    def test_name_taken_in_another_org_does_not_count(self, graph, default_org):
        name = graph.name
        other_org = type(default_org).objects.create(name="Other org")
        graph.delete()
        Graph.objects.create(org=other_org, name=name)

        result = RestoreService.restore(_binned(Graph, graph.pk))

        assert result.renamed_from is None
        assert result.object.name == name


@pytest.mark.django_db
class TestRestoreRunsSaveSignals:
    """Models with a post_save receiver are restored per row, so their receivers
    re-register what the delete unregistered."""

    def test_schedule_trigger_is_republished(self, graph, mocker, django_capture_on_commit_callbacks):
        ScheduleTriggerNode.objects.create(graph=graph, node_name="cron", is_active=True)
        graph.delete()
        redis_service = mocker.patch("tables.signals.schedule_signals.RedisService")

        with django_capture_on_commit_callbacks(execute=True):
            RestoreService.restore(_binned(Graph, graph.pk))

        redis_service.return_value.redis_client.publish.assert_called_once()

    def test_telegram_trigger_is_registered_again_with_its_auth(
        self, graph, mocker, django_capture_on_commit_callbacks
    ):
        # Real trigger and auth, and the delete's on_commit cleanup really runs:
        # a binned node must keep the auth that holds the bot secret.
        register = mocker.patch.object(TelegramTriggerService, "register_telegram_trigger", return_value={"ok": True})
        secret = Secret(org=graph.org, name="restore-telegram-key")
        secret_encryption.encrypt(text="12345:fake_key").write_to(secret)
        secret.save()
        trigger = WebhookTrigger.objects.create(path="restore-telegram", provider_type=None, org=graph.org)
        WebhookTriggerAuth.objects.create(trigger=trigger, kind=WebhookTriggerAuthKind.TELEGRAM)
        node = TelegramTriggerNode.objects.create(
            node_name="bot", telegram_bot_api_key_secret=secret, graph=graph, webhook_trigger=trigger
        )
        with django_capture_on_commit_callbacks(execute=True):
            graph.delete()
        register.reset_mock()

        with django_capture_on_commit_callbacks(execute=True):
            RestoreService.restore(_binned(Graph, graph.pk))

        register.assert_called_once()
        assert register.call_args.kwargs["telegram_trigger_instance"].pk == node.pk
        assert WebhookTriggerAuth.objects.filter(trigger=trigger, kind=WebhookTriggerAuthKind.TELEGRAM).exists()

def test_every_registered_resource_points_at_real_fields():
    for model in (Graph, PythonCodeTool, SourceCollection):
        resource = bin_resource_for(model)
        model._meta.get_field(resource.name_field)
        model._meta.get_field(resource.org_field)


@pytest.mark.django_db(transaction=True)
def test_concurrent_restores_of_same_named_flows_pick_different_names():
    # Without the name lock both restores would pick "Flow #2" and the second
    # would hit the unique constraint.
    org = Organization.objects.create(name="Org RestoreRace")
    first = Graph.objects.create(org=org, name="Flow")
    first.delete()
    second = Graph.objects.create(org=org, name="Flow")
    second.delete()
    Graph.objects.create(org=org, name="Flow")

    outcomes = run_concurrently(
        [
            lambda: RestoreService.restore(_binned(Graph, first.pk)).object.name,
            lambda: RestoreService.restore(_binned(Graph, second.pk)).object.name,
        ]
    )

    for outcome in outcomes:
        assert not isinstance(outcome, Exception), outcome
    assert set(outcomes) == {"Flow #2", "Flow #3"}


@pytest.mark.django_db
class TestPurgeOnlyRemovesBinnedRows:
    def test_purge_refuses_a_live_row(self, graph):
        with pytest.raises(NotInRecycleBinError):
            graph.purge()

        assert Graph.objects.filter(pk=graph.pk).exists()

    def test_purge_after_a_restore_does_not_delete_the_restored_flow(self, graph):
        # A purge request that loaded the flow while it was binned, and runs
        # after a restore committed, must not delete the now-live flow.
        graph.delete()
        stale_copy = _binned(Graph, graph.pk)
        RestoreService.restore(_binned(Graph, graph.pk))

        with pytest.raises(NotInRecycleBinError):
            stale_copy.purge()

        assert Graph.objects.filter(pk=graph.pk).exists()
