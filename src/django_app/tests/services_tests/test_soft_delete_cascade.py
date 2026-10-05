"""Tests for the generic, introspection-based soft-delete cascade mechanism
(`tables.services.soft_delete.DeleteService`) and the `SoftDeleteFields` /
`SoftDeleteMixin` base classes it operates on.

Covers, per root and per mechanism rule:
- Full cascade through a multi-level subtree on `delete()` (always soft).
- `purge()` removes a root and its whole subtree, binned rows included.
- A model with only `SoftDeleteFields` (no `SoftDeleteMixin`) always hard-deletes
  on a direct `.delete()`.
- `Session.graph` is nulled rather than cascaded (nullable-fallback branch).
- Forward-FK targets (`PythonCode`, `DocumentContent`, `GraphRagIndexConfig`)
  are never visited by the reverse-relation walker.
- `ScheduleTriggerNode.is_active` (business field) is untouched by the cascade,
  distinct from `active` (soft-delete field) on the same model.
- The PROTECT/RESTRICT/DO_NOTHING guards in `_DeleteContext._process_related_object`.
"""

import json
from unittest.mock import MagicMock

import pytest
from django.apps import apps
from django.db import connection, models
from django.db.models.deletion import ProtectedError, RestrictedError
from django.core.exceptions import ImproperlyConfigured
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from agents.models import (
    InlineSurface,
    InlineSurfaceKnowledge,
    InlineSurfacePythonTool,
    Surface,
    SurfacePythonTool,
    ToolMode,
)
from django_app.settings import SCHEDULE_CHANNEL
from tables.models import (
    BaseRagType,
    DocumentContent,
    DocumentMetadata,
    Graph,
    GraphNote,
    GraphVersion,
    KnowledgeNode,
    PythonCode,
    PythonNode,
    ScheduleTriggerNode,
    Session,
    SourceCollection,
    TaskNode,
    WebhookTriggerNode,
)
from tables.models import Agent, AgentNode, AgentNodeTask, Edge, SubGraphNode
from tables.models.knowledge_models.naive_rag_models import AgentNaiveRag, NaiveRag
from tables.models.label_models import Label
from tables.models.base_models import SoftDeleteFields
from tables.models.session_models import SessionTrigger
from tables.models.webhook_models import (
    WebhookTrigger,
    WebhookTriggerAuth,
    WebhookTriggerAuthKind,
)
from tables.models.knowledge_models.graphrag_models import (
    GraphRag,
    GraphRagDocument,
    GraphRagIndexConfig,
)
from tables.services.soft_delete import DeleteService, _DeleteContext


@pytest.mark.django_db
class TestFullCascadePerRoot:
    """Item 1: soft-deleting each root cascades through its full subtree."""

    def test_graph_cascades_through_task_node_inline_surface_knowledge(
        self, graph, default_org
    ):
        task_node = TaskNode.objects.create(graph=graph, node_name="task_1")
        inline_surface = InlineSurface.objects.create(task_node=task_node)
        # The knowledge collection is a forward-FK target of InlineSurfaceKnowledge,
        # not a descendant of `graph` — it must stay untouched by this cascade.
        attached_collection = SourceCollection.objects.create(
            org=default_org, collection_name="Attached KB"
        )
        inline_surface_knowledge = InlineSurfaceKnowledge.objects.create(
            inline_surface=inline_surface, collection=attached_collection
        )

        graph.delete()

        graph.refresh_from_db()
        task_node.refresh_from_db()
        inline_surface.refresh_from_db()
        inline_surface_knowledge.refresh_from_db()
        attached_collection.refresh_from_db()

        for obj in (graph, task_node, inline_surface, inline_surface_knowledge):
            assert obj.active is False
            assert obj.soft_deleted_at is not None

        assert attached_collection.active is True
        assert attached_collection.soft_deleted_at is None

    def test_source_collection_cascades_through_document_and_graph_rag(
        self, default_org
    ):
        collection = SourceCollection.objects.create(
            org=default_org, collection_name="Docs KB"
        )
        document_content = DocumentContent.objects.create(content=b"payload")
        document = DocumentMetadata.objects.create(
            source_collection=collection,
            document_content=document_content,
            file_name="report.txt",
            file_type=DocumentMetadata.DocumentFileType.TXT,
            file_size=7,
        )
        base_rag_type = BaseRagType.objects.create(
            source_collection=collection, rag_type=BaseRagType.RagType.GRAPH
        )
        graph_rag = GraphRag.objects.create(base_rag_type=base_rag_type)
        graph_rag_document = GraphRagDocument.objects.create(
            graph_rag=graph_rag, document=document
        )

        collection.delete()

        collection.refresh_from_db()
        document.refresh_from_db()
        base_rag_type.refresh_from_db()
        graph_rag.refresh_from_db()
        graph_rag_document.refresh_from_db()

        for obj in (collection, document, base_rag_type, graph_rag, graph_rag_document):
            assert obj.active is False
            assert obj.soft_deleted_at is not None

        # DocumentContent is a forward-FK target of DocumentMetadata — never visited.
        document_content.refresh_from_db()
        assert not isinstance(document_content, SoftDeleteFields)

    def test_python_code_tool_cascades_through_config(
        self, python_code_tool, python_code_tool_config
    ):
        python_code_tool.delete()

        python_code_tool.refresh_from_db()
        python_code_tool_config.refresh_from_db()

        assert python_code_tool.active is False
        assert python_code_tool.soft_deleted_at is not None
        assert python_code_tool_config.active is False
        assert python_code_tool_config.soft_deleted_at is not None

    def test_graph_cascades_through_knowledge_node(self, graph):
        """EST-3788 review item 6: KnowledgeNode previously lacked
        SoftDeleteFields entirely, so its sole reverse-CASCADE handling
        fell through to `_hard_delete` — a graph soft-delete would
        permanently destroy its KnowledgeNode children while every other
        node type on the graph survived as a soft-deleted row. KnowledgeNode
        now carries SoftDeleteFields like the other node types, so it must
        soft-delete and remain queryable via `all_objects`."""
        knowledge_node = KnowledgeNode.objects.create(graph=graph)

        graph.delete()

        knowledge_node.refresh_from_db()
        assert knowledge_node.active is False
        assert knowledge_node.soft_deleted_at is not None
        assert KnowledgeNode.all_objects.filter(pk=knowledge_node.pk).exists()

    def test_graph_version_soft_deletes(self, graph):
        """GraphVersion has no reverse-relation descendants of its own — the
        cascade mechanism still needs to soft-delete the root object itself."""
        version = GraphVersion.objects.create(
            graph=graph, name="v1", snapshot={}, dependencies={}
        )

        version.delete()

        version.refresh_from_db()
        assert version.active is False
        assert version.soft_deleted_at is not None


@pytest.mark.django_db
class TestPurgePath:
    """`delete()` on a root always moves it to the recycle bin; `purge()` removes
    it for good through Django's Collector, binned subtree rows included."""

    def test_delete_is_soft_without_any_setting(self, graph):
        task_node = TaskNode.objects.create(graph=graph, node_name="task_1")

        graph.delete()

        assert Graph.deleted_objects.filter(id=graph.id).exists()
        assert TaskNode.deleted_objects.filter(id=task_node.id).exists()

    def test_purge_removes_binned_subtree_but_not_forward_fk_targets(self, graph, default_org):
        task_node = TaskNode.objects.create(graph=graph, node_name="task_1")
        inline_surface = InlineSurface.objects.create(task_node=task_node)
        attached_collection = SourceCollection.objects.create(
            org=default_org, collection_name="Attached KB"
        )
        inline_surface_knowledge = InlineSurfaceKnowledge.objects.create(
            inline_surface=inline_surface, collection=attached_collection
        )
        graph.delete()

        Graph.all_objects.get(id=graph.id).purge()

        assert not Graph.all_objects.filter(id=graph.id).exists()
        assert not TaskNode.all_objects.filter(id=task_node.id).exists()
        assert not InlineSurface.all_objects.filter(id=inline_surface.id).exists()
        assert not InlineSurfaceKnowledge.all_objects.filter(id=inline_surface_knowledge.id).exists()
        # Forward-FK target: the Collector never reaches it.
        assert SourceCollection.all_objects.filter(
            collection_id=attached_collection.collection_id
        ).exists()


@pytest.mark.django_db
class TestDirectDeleteOnGroup2OnlyModel:
    """Item 3: a model with only `SoftDeleteFields` (no `SoftDeleteMixin`)
    always performs a normal hard delete on a direct `.delete()` call, because
    it never overrides `delete()`."""

    def test_direct_delete_on_task_node_is_always_hard_delete(self, graph):
        task_node = TaskNode.objects.create(graph=graph, node_name="standalone_task")
        task_node_id = task_node.id

        task_node.delete()

        assert not TaskNode.all_objects.filter(id=task_node_id).exists()


@pytest.mark.django_db
class TestSessionGraphNulledNotCascaded:
    """Item 4: `Session.graph` is CASCADE + nullable. The nullable-fallback
    branch in `_process_related_object` fires before the CASCADE branch, so
    the Session survives with its FK cleared instead of being hard-deleted."""

    def test_session_survives_graph_soft_delete_with_graph_id_nulled(self, graph):
        session = Session.objects.create(
            graph=graph,
            status=Session.SessionStatus.PENDING,
            status_updated_at=timezone.now(),
        )
        session_id = session.id

        graph.delete()

        session.refresh_from_db()
        assert Session.objects.filter(id=session_id).exists()
        assert session.graph_id is None


@pytest.mark.django_db
class TestForwardFkExclusions:
    """Item 5: forward-FK targets are reached from their owner going forward,
    not backward — the reverse-relation walker never visits them, so they
    stay untouched even when their sole owner is soft-deleted."""

    def test_python_code_untouched_by_owning_graph_soft_delete(self, graph):
        code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
        python_node = PythonNode.objects.create(graph=graph, python_code=code)

        graph.delete()

        python_node.refresh_from_db()
        assert python_node.active is False

        code.refresh_from_db()
        assert not isinstance(code, SoftDeleteFields)
        assert PythonCode.objects.filter(pk=code.pk).exists()

    def test_document_content_untouched_by_owning_collection_soft_delete(
        self, default_org
    ):
        collection = SourceCollection.objects.create(
            org=default_org, collection_name="Docs KB 2"
        )
        content = DocumentContent.objects.create(content=b"keep me")
        document = DocumentMetadata.objects.create(
            source_collection=collection,
            document_content=content,
            file_name="keep_me.txt",
            file_type=DocumentMetadata.DocumentFileType.TXT,
            file_size=8,
        )

        collection.delete()

        document.refresh_from_db()
        assert document.active is False

        content.refresh_from_db()
        assert not isinstance(content, SoftDeleteFields)
        assert DocumentContent.objects.filter(pk=content.pk).exists()

    def test_graph_rag_index_config_untouched_by_owning_collection_soft_delete(
        self, default_org
    ):
        collection = SourceCollection.objects.create(
            org=default_org, collection_name="Docs KB 3"
        )
        base_rag_type = BaseRagType.objects.create(
            source_collection=collection, rag_type=BaseRagType.RagType.GRAPH
        )
        index_config = GraphRagIndexConfig.objects.create()
        graph_rag = GraphRag.objects.create(
            base_rag_type=base_rag_type, index_config=index_config
        )

        collection.delete()

        graph_rag.refresh_from_db()
        assert graph_rag.active is False

        index_config.refresh_from_db()
        assert not isinstance(index_config, SoftDeleteFields)
        assert GraphRagIndexConfig.objects.filter(pk=index_config.pk).exists()


@pytest.mark.django_db
class TestScheduleTriggerNodeIsActiveUntouched:
    """Item 6: `ScheduleTriggerNode.is_active` is its own business field
    (enabled/disabled). It must not collide with the cascade's
    `active` field on the same model."""

    def test_is_active_business_field_survives_cascade(self, graph):
        node = ScheduleTriggerNode.objects.create(
            graph=graph, node_name="trigger_node", is_active=True
        )

        graph.delete()

        node.refresh_from_db()
        assert node.is_active is True
        assert node.active is False
        assert node.soft_deleted_at is not None


@pytest.mark.django_db
class TestHiddenReverseRelationSetNull:
    """Item 9 (EST-3788 review): related_name="+" reverse relations are
    hidden from Model._meta.get_fields() by default, so
    SessionTrigger.schedule_trigger_node (SET_NULL) was previously invisible
    to the cascade walker — the FK never got nulled out when its
    ScheduleTriggerNode was soft-deleted. _get_reverse_relations now passes
    include_hidden=True and _get_related_objects fetches hidden relations
    via a direct queryset filter (no reverse accessor exists for them).

    ScheduleTriggerNode only has `SoftDeleteFields` (no `SoftDeleteMixin`),
    so a direct `.delete()` on it is always a hard delete (see
    TestDirectDeleteOnGroup2OnlyModel). To exercise the cascade path we
    soft-delete via the graph root, exactly like
    TestScheduleTriggerNodeIsActiveUntouched does."""

    def test_schedule_trigger_node_soft_delete_nulls_session_trigger_fk(self, graph):
        node = ScheduleTriggerNode.objects.create(
            graph=graph, node_name="trigger_node", is_active=True
        )
        session = Session.objects.create(
            status=Session.SessionStatus.PENDING,
            status_updated_at=timezone.now(),
        )
        trigger = SessionTrigger.objects.create(
            session=session,
            trigger_type=SessionTrigger.TriggerType.SCHEDULE,
            schedule_trigger_node=node,
        )

        graph.delete()

        node.refresh_from_db()
        assert node.active is False
        assert node.soft_deleted_at is not None

        trigger.refresh_from_db()
        assert trigger.schedule_trigger_node_id is None

        session.refresh_from_db()
        assert SessionTrigger.objects.filter(pk=trigger.pk).exists()
        assert Session.objects.filter(pk=session.pk).exists()

    def test_webhook_trigger_node_soft_delete_nulls_session_trigger_fk(self, graph):
        python_code = PythonCode.objects.create(
            code="def main(): return 1", entrypoint="main"
        )
        webhook_trigger = WebhookTrigger.objects.create(
            path="trigger-node-path", org=graph.org
        )
        node = WebhookTriggerNode.objects.create(
            graph=graph,
            node_name="trigger_node",
            python_code=python_code,
            webhook_trigger=webhook_trigger,
        )
        # WebhookTriggerNode's post_save signal (tables/signals/webhook_signals.py)
        # no longer auto-creates auth -- a WebhookTriggerAuth row only exists
        # once explicitly configured via WebhookTriggerService, so we create
        # one directly here to exercise the cascade against it.
        node_auth = WebhookTriggerAuth.objects.create(
            trigger=webhook_trigger, kind=WebhookTriggerAuthKind.WEBHOOK
        )
        session = Session.objects.create(
            status=Session.SessionStatus.PENDING,
            status_updated_at=timezone.now(),
        )
        trigger = SessionTrigger.objects.create(
            session=session,
            trigger_type=SessionTrigger.TriggerType.WEBHOOK,
            webhook_trigger_node=node,
        )

        graph.delete()

        node.refresh_from_db()
        assert node.active is False
        assert node.soft_deleted_at is not None

        trigger.refresh_from_db()
        assert trigger.webhook_trigger_node_id is None

        session.refresh_from_db()
        assert SessionTrigger.objects.filter(pk=trigger.pk).exists()
        assert Session.objects.filter(pk=session.pk).exists()

        # WebhookTriggerAuth carries SoftDeleteFields, so when the graph
        # cascade reaches WebhookTrigger (via WebhookTriggerNode.webhook_trigger,
        # a SET_NULL FK that only nulls out -- the trigger row itself is
        # untouched by this cascade) it is the auth row's own FK to
        # WebhookTriggerNode's graph subtree that matters here: the auth is
        # keyed off `trigger`, not off the node, so it is unaffected by the
        # node's soft-delete and remains fully active.
        node_auth.refresh_from_db()
        assert node_auth.active is True
        assert node_auth.soft_deleted_at is None
        assert WebhookTriggerAuth.objects.filter(pk=node_auth.pk).exists()
        assert node_auth.trigger_id == webhook_trigger.pk


class TestProtectRestrictDoNothingGuards:
    """Item 8: the project has no real PROTECT/RESTRICT/DO_NOTHING relation
    anywhere in its schema today (verified by grep), and adding one would
    require a new model + migration, which is out of scope here (code-only,
    no makemigrations/migrate). We exercise the actual guard branches in
    `_DeleteContext._process_related_object` directly against mocked
    child/relation objects instead of skipping this coverage silently."""

    def test_protect_raises_protected_error(self):
        context = _DeleteContext()
        parent = MagicMock(spec=[])
        child = MagicMock(spec=[])  # not a SoftDeleteFields instance
        relation = MagicMock()
        relation.field.remote_field.on_delete = models.PROTECT

        with pytest.raises(ProtectedError):
            context._process_related_object(
                parent=parent, child=child, relation=relation
            )

    def test_restrict_raises_restricted_error(self):
        context = _DeleteContext()
        parent = MagicMock(spec=[])
        child = MagicMock(spec=[])
        relation = MagicMock()
        relation.field.remote_field.on_delete = models.RESTRICT

        with pytest.raises(RestrictedError):
            context._process_related_object(
                parent=parent, child=child, relation=relation
            )

    def test_do_nothing_on_non_nullable_field_raises_improperly_configured(self):
        context = _DeleteContext()
        parent = MagicMock(spec=[])
        child = MagicMock(spec=[])
        relation = MagicMock()
        relation.field.remote_field.on_delete = models.DO_NOTHING
        relation.field.null = False

        with pytest.raises(ImproperlyConfigured):
            context._process_related_object(
                parent=parent, child=child, relation=relation
            )

    @pytest.mark.django_db
    def test_protect_relation_rolls_back_the_whole_transaction(self, mocker, graph):
        """Integration check: inject a synthetic PROTECT relation into a real
        Graph's reverse-relation walk (via monkeypatching, since no real
        PROTECT relation exists to exercise this through) and confirm
        `DeleteService.delete()` propagates the error and the transaction
        rolls back — the graph is not left in a partially soft-deleted state."""
        fake_relation = MagicMock()
        fake_relation.field.remote_field.on_delete = models.PROTECT
        fake_child = MagicMock(spec=[])

        mocker.patch.object(
            _DeleteContext,
            "_get_reverse_relations",
            return_value=[fake_relation],
        )
        mocker.patch.object(
            _DeleteContext,
            "_get_related_objects",
            return_value=[fake_child],
        )

        with pytest.raises(ProtectedError):
            DeleteService.delete(graph)

        graph.refresh_from_db()
        assert graph.active is True
        assert graph.soft_deleted_at is None


@pytest.mark.django_db
class TestPostSaveListenerModelsBypassBatching:
    """A reverse relation to a model with a post_save receiver must never be
    routed through `_batch_soft_delete_cascade`'s `QuerySet.update()`, since
    that call never fires `post_save`. `ScheduleTriggerNode`,
    `WebhookTriggerNode` and `TelegramTriggerNode` publish a Redis event for
    the Manager service on every save via such a receiver
    (`tables/signals/schedule_signals.py`,
    `tables/signals/webhook_signals.py`,
    `tables/signals/telegram_signals.py`). `_is_soft_delete_cascade_relation`
    now returns False for these, sending them through the per-object
    `_process_related_object` -> `_handle_cascade` -> `DeleteService.delete`
    path instead, whose `_soft_delete` calls `obj.save()` and therefore
    still triggers the signal."""

    def test_schedule_trigger_node_post_save_signal_fires_on_cascaded_soft_delete(
        self, graph, redis_client_mock, django_capture_on_commit_callbacks
    ):
        # The "create" publish from objects.create() is queued for a commit that
        # never comes; only the cascade's own publish runs inside the capture below.
        node = ScheduleTriggerNode.objects.create(
            graph=graph, node_name="trigger_node", is_active=True
        )

        with django_capture_on_commit_callbacks(execute=True):
            graph.delete()

        node.refresh_from_db()
        assert node.active is False
        assert node.soft_deleted_at is not None

        assert redis_client_mock.publish.called
        channel, payload = redis_client_mock.publish.call_args.args
        assert channel == SCHEDULE_CHANNEL

        message = json.loads(payload)
        assert message["data"]["action"] == "update"
        assert message["data"]["node"]["id"] == node.pk

    def test_webhook_trigger_node_soft_delete_still_soft_deletes_on_cascade(
        self, graph, redis_client_mock
    ):
        """webhook_signals' post_save handler talks to the `webhook` service
        over HTTP rather than Redis, so it isn't asserted directly here (that
        would require mocking an HTTP client). This test instead locks in the
        outcome that matters for this change: the node is still soft-deleted
        correctly now that it takes the per-object path instead of the
        batched UPDATE."""
        python_code = PythonCode.objects.create(
            code="def main(): return 1", entrypoint="main"
        )
        node = WebhookTriggerNode.objects.create(
            graph=graph, node_name="trigger_node", python_code=python_code
        )

        graph.delete()

        node.refresh_from_db()
        assert node.active is False
        assert node.soft_deleted_at is not None


@pytest.mark.django_db
class TestBatchedCascadeQueryCountDoesNotGrowWithChildCount:
    """The batched-UPDATE optimization in `_batch_soft_delete_cascade` must
    keep issuing a single UPDATE per model regardless of how many children
    are soft-deleted through it. Compares total query count for a small vs.
    a large batch of plain (no post_save receiver, no M2M or reverse-relation
    descendants of its own) `GraphNote` children of the same `Graph` root —
    no growth confirms the batch path, not one `.save()` per object, is
    still in effect. `TaskNode` is deliberately avoided here: each one has its
    own reverse relations (its inline surface), walked per object, which
    would make query count grow for reasons unrelated to what this test
    checks."""

    def test_graph_note_cascade_query_count_is_flat(self, default_org):
        small_graph = Graph.objects.create(name="small-batch-graph", org=default_org)
        for index in range(2):
            GraphNote.objects.create(graph=small_graph, content=f"note_{index}")

        with CaptureQueriesContext(connection) as few:
            small_graph.delete()

        large_graph = Graph.objects.create(name="large-batch-graph", org=default_org)
        for index in range(20):
            GraphNote.objects.create(graph=large_graph, content=f"note_{index}")

        with CaptureQueriesContext(connection) as many:
            large_graph.delete()

        assert len(many) == len(few), "\n".join(
            query["sql"] for query in many.captured_queries
        )


@pytest.mark.django_db
class TestSoftDeleteBatch:
    """One DeleteService.delete() call stamps one batch id and one timestamp on
    every row it bins, so restore can bring back exactly that delete."""

    def test_root_and_every_child_share_one_batch_and_timestamp(self, graph):
        task_node = TaskNode.objects.create(graph=graph, node_name="task")
        edge = Edge.objects.create(graph=graph)
        # A post_save listener sends this model through the per-row path,
        # while the task node and edge go through the batched UPDATE.
        schedule_node = ScheduleTriggerNode.objects.create(graph=graph, node_name="cron")

        batch = DeleteService.delete(graph)

        rows = [
            Graph.all_objects.get(pk=graph.pk),
            TaskNode.all_objects.get(pk=task_node.pk),
            Edge.all_objects.get(pk=edge.pk),
            ScheduleTriggerNode.all_objects.get(pk=schedule_node.pk),
        ]
        assert batch is not None
        assert {row.soft_delete_batch for row in rows} == {batch}
        assert len({row.soft_deleted_at for row in rows}) == 1

    def test_separate_deletes_get_separate_batches(self, graph):
        task_node = TaskNode.objects.create(graph=graph, node_name="task")

        node_batch = DeleteService.delete(task_node)
        graph_batch = DeleteService.delete(graph)

        assert node_batch != graph_batch
        assert TaskNode.all_objects.get(pk=task_node.pk).soft_delete_batch == node_batch
        assert Graph.all_objects.get(pk=graph.pk).soft_delete_batch == graph_batch

    def test_soft_delete_returns_the_batch(self, graph):
        batch = graph.soft_delete()

        assert Graph.all_objects.get(pk=graph.pk).soft_delete_batch == batch

    def test_a_row_binned_on_its_own_keeps_its_batch_when_its_parent_is_deleted(self, graph):
        # ScheduleTriggerNode goes through the per-row path (post_save listener).
        schedule_node = ScheduleTriggerNode.objects.create(graph=graph, node_name="cron")
        node_batch = DeleteService.delete(schedule_node)

        graph_batch = DeleteService.delete(graph)

        assert node_batch != graph_batch
        assert ScheduleTriggerNode.all_objects.get(pk=schedule_node.pk).soft_delete_batch == node_batch

    def test_deleting_an_already_binned_root_changes_nothing(self, graph):
        # A second request (a double-click) loaded the flow before the first one binned it.
        stale_graph = Graph.objects.get(pk=graph.pk)
        first_batch = DeleteService.delete(graph)
        first_deleted_at = Graph.all_objects.get(pk=graph.pk).soft_deleted_at

        second_batch = DeleteService.delete(stale_graph)

        binned_graph = Graph.all_objects.get(pk=graph.pk)
        assert second_batch is None
        assert binned_graph.soft_delete_batch == first_batch
        assert binned_graph.soft_deleted_at == first_deleted_at


def _context_link_exists(task: AgentNodeTask, context_task: AgentNodeTask) -> bool:
    # Through the link table: the related manager would hide binned tasks.
    return AgentNodeTask.context_tasks.through.objects.filter(
        from_agentnodetask_id=task.pk, to_agentnodetask_id=context_task.pk
    ).exists()


@pytest.mark.django_db
class TestManyToManyOnDelete:
    """A deleted row keeps its own M2M links (restore needs them). Links from
    rows outside its batch are removed, so those rows don't point into the bin."""

    def test_flow_keeps_its_own_labels(self, graph):
        label = Label.objects.create(name="prod", org=graph.org)
        graph.labels.add(label)

        graph.delete()

        assert list(Graph.all_objects.get(pk=graph.pk).labels.all()) == [label]

    def test_links_between_rows_of_one_batch_survive(self, graph):
        agent_node = AgentNode.objects.create(graph=graph, node_name="agent")
        first_task = AgentNodeTask.objects.create(agent_node=agent_node, name="first", order=0)
        second_task = AgentNodeTask.objects.create(agent_node=agent_node, name="second", order=1)
        second_task.context_tasks.add(first_task)

        graph.delete()

        assert _context_link_exists(second_task, first_task)

    def test_incoming_link_from_outside_the_batch_is_removed_own_link_kept(self, graph):
        agent_node = AgentNode.objects.create(graph=graph, node_name="agent")
        binned_task = AgentNodeTask.objects.create(agent_node=agent_node, name="binned", order=0)
        live_task = AgentNodeTask.objects.create(agent_node=agent_node, name="live", order=1)
        earlier_task = AgentNodeTask.objects.create(agent_node=agent_node, name="earlier", order=2)
        live_task.context_tasks.add(binned_task)
        binned_task.context_tasks.add(earlier_task)

        DeleteService.delete(binned_task)

        assert AgentNodeTask.deleted_objects.filter(pk=binned_task.pk).exists()
        assert AgentNodeTask.objects.filter(pk=live_task.pk).exists()
        assert not _context_link_exists(live_task, binned_task)
        assert _context_link_exists(binned_task, earlier_task)

    def test_link_between_two_separately_binned_rows_survives(self, graph):
        agent_node = AgentNode.objects.create(graph=graph, node_name="agent")
        first_binned = AgentNodeTask.objects.create(agent_node=agent_node, name="first", order=0)
        later_binned = AgentNodeTask.objects.create(agent_node=agent_node, name="later", order=1)
        first_binned.context_tasks.add(later_binned)
        DeleteService.delete(first_binned)

        DeleteService.delete(later_binned)

        # Restoring `first_binned` must bring its own link back.
        assert _context_link_exists(first_binned, later_binned)

    def test_flow_delete_query_count_does_not_grow_with_linked_tasks(self, default_org):
        def flow_with_linked_tasks(name, task_count):
            flow = Graph.objects.create(name=name, org=default_org)
            agent_node = AgentNode.objects.create(graph=flow, node_name="agent")
            tasks = [
                AgentNodeTask.objects.create(agent_node=agent_node, name=f"task_{index}", order=index)
                for index in range(task_count)
            ]
            for task, context_task in zip(tasks[1:], tasks):
                task.context_tasks.add(context_task)
            return flow

        small_flow = flow_with_linked_tasks("small-linked-flow", 2)
        large_flow = flow_with_linked_tasks("large-linked-flow", 20)

        with CaptureQueriesContext(connection) as few:
            small_flow.delete()
        with CaptureQueriesContext(connection) as many:
            large_flow.delete()

        assert len(many) == len(few), "\n".join(query["sql"] for query in many.captured_queries)


@pytest.mark.django_db
class TestReferencesFromBinnedRowsAreDropped:
    """SET_NULL also reaches rows already in the recycle bin: otherwise a
    restored row comes back pointing at something deleted while it was binned."""

    def test_binned_flow_subflow_node_loses_subflow_deleted_later(self, graph):
        subflow = Graph.objects.create(org=graph.org, name="Sub")
        subflow_node = SubGraphNode.objects.create(graph=graph, node_name="sub", subgraph=subflow)
        graph.delete()

        subflow.delete()

        assert SubGraphNode.all_objects.get(pk=subflow_node.pk).subgraph_id is None

    def test_binned_flow_knowledge_node_loses_collection_deleted_later(self, graph, default_org):
        collection = SourceCollection.objects.create(org=default_org, collection_name="Docs")
        knowledge_node = KnowledgeNode.objects.create(graph=graph, source_collection=collection)
        graph.delete()

        collection.delete()

        assert KnowledgeNode.all_objects.get(pk=knowledge_node.pk).source_collection_id is None


@pytest.mark.django_db
class TestChildrenBinnedEarlierAreLeftAlone:
    """A child binned on its own had its subtree handled then. The parent's
    delete marks it visited without walking into it again or re-stamping it."""

    def test_flow_delete_does_not_walk_into_children_binned_earlier(self, default_org):
        def flow_with_binned_task_nodes(name, node_count):
            flow = Graph.objects.create(name=name, org=default_org)
            node_batches = {}
            for index in range(node_count):
                task_node = TaskNode.objects.create(graph=flow, node_name=f"task_{index}")
                node_batches[task_node.pk] = DeleteService.delete(task_node)
            return flow, node_batches

        small_flow, _ = flow_with_binned_task_nodes("small-binned-flow", 2)
        large_flow, large_node_batches = flow_with_binned_task_nodes("large-binned-flow", 20)

        with CaptureQueriesContext(connection) as few:
            small_flow.delete()
        with CaptureQueriesContext(connection) as many:
            large_flow.delete()

        assert len(many) == len(few), "\n".join(query["sql"] for query in many.captured_queries)
        assert dict(
            TaskNode.all_objects.filter(pk__in=large_node_batches).values_list("pk", "soft_delete_batch")
        ) == large_node_batches

    def test_per_row_child_binned_earlier_is_not_saved_again(self, graph, mocker):
        # ScheduleTriggerNode has a post_save listener, so it goes through the
        # per-row path; a second save() would republish it to the Manager.
        schedule_node = ScheduleTriggerNode.objects.create(graph=graph, node_name="cron")
        node_batch = DeleteService.delete(schedule_node)
        binned_at = ScheduleTriggerNode.all_objects.get(pk=schedule_node.pk).soft_deleted_at
        redis_service = mocker.patch("tables.signals.schedule_signals.RedisService")

        graph.delete()

        binned_node = ScheduleTriggerNode.all_objects.get(pk=schedule_node.pk)
        assert binned_node.soft_delete_batch == node_batch
        assert binned_node.soft_deleted_at == binned_at
        redis_service.return_value.redis_client.publish.assert_not_called()

    def test_stale_copy_of_a_restored_root_is_binned(self, graph):
        # The caller's instance was loaded while the flow was binned; the flow
        # has been restored since. Its delete() must bin it, not return early.
        graph.delete()
        Graph.all_objects.filter(pk=graph.pk).update(active=True, soft_deleted_at=None, soft_delete_batch=None)

        batch = DeleteService.delete(graph)

        assert batch is not None
        assert Graph.all_objects.get(pk=graph.pk).soft_delete_batch == batch


@pytest.mark.django_db
class TestOwnerVersusReferenceLinks:
    """A link row that only points at the deleted row (a surface using a tool)
    is removed for good, so restoring the target never re-links it. A link
    row that belongs to the deleted row goes to the bin in the same batch."""

    def test_tool_delete_removes_surface_links(self, python_code_tool, default_org, graph):
        surface = Surface.objects.create(organization=default_org, name="S")
        surface_link = SurfacePythonTool.objects.create(
            surface=surface, python_tool=python_code_tool, mode=ToolMode.ALLOW
        )
        inline_surface = InlineSurface.objects.create(
            task_node=TaskNode.objects.create(graph=graph, node_name="t")
        )
        inline_link = InlineSurfacePythonTool.objects.create(
            inline_surface=inline_surface, python_tool=python_code_tool, mode=ToolMode.ALLOW
        )

        python_code_tool.delete()

        assert not SurfacePythonTool.all_objects.filter(pk=surface_link.pk).exists()
        assert not InlineSurfacePythonTool.all_objects.filter(pk=inline_link.pk).exists()

    def test_tool_delete_removes_link_from_a_binned_flow(self, python_code_tool, graph):
        inline_surface = InlineSurface.objects.create(
            task_node=TaskNode.objects.create(graph=graph, node_name="t")
        )
        inline_link = InlineSurfacePythonTool.objects.create(
            inline_surface=inline_surface, python_tool=python_code_tool, mode=ToolMode.ALLOW
        )
        graph.delete()

        python_code_tool.delete()

        assert not InlineSurfacePythonTool.all_objects.filter(pk=inline_link.pk).exists()

    def test_collection_delete_removes_knowledge_link(self, default_org, graph):
        collection = SourceCollection.objects.create(org=default_org, collection_name="KB")
        inline_surface = InlineSurface.objects.create(
            task_node=TaskNode.objects.create(graph=graph, node_name="t")
        )
        knowledge_link = InlineSurfaceKnowledge.objects.create(
            inline_surface=inline_surface, collection=collection
        )

        collection.delete()

        assert not InlineSurfaceKnowledge.all_objects.filter(pk=knowledge_link.pk).exists()

    def test_owner_delete_keeps_its_links_in_the_batch(self, python_code_tool, default_org, graph):
        inline_surface = InlineSurface.objects.create(
            task_node=TaskNode.objects.create(graph=graph, node_name="t")
        )
        tool_link = InlineSurfacePythonTool.objects.create(
            inline_surface=inline_surface, python_tool=python_code_tool, mode=ToolMode.ALLOW
        )
        knowledge_link = InlineSurfaceKnowledge.objects.create(
            inline_surface=inline_surface,
            collection=SourceCollection.objects.create(org=default_org, collection_name="KB"),
        )

        batch = graph.delete()

        assert InlineSurfacePythonTool.all_objects.get(pk=tool_link.pk).soft_delete_batch == batch
        assert InlineSurfaceKnowledge.all_objects.get(pk=knowledge_link.pk).soft_delete_batch == batch

    def test_collection_delete_drops_the_agent_rag_link(self, default_org):
        agent = Agent.objects.create(role="tester", goal="goal", org=default_org)
        collection = SourceCollection.objects.create(org=default_org, collection_name="KB")
        base_rag_type = BaseRagType.objects.create(
            rag_type=BaseRagType.RagType.NAIVE, source_collection=collection
        )
        naive_rag = NaiveRag.objects.create(base_rag_type=base_rag_type)
        link = AgentNaiveRag.objects.create(agent=agent, naive_rag=naive_rag)

        collection.delete()

        assert not AgentNaiveRag.all_objects.filter(pk=link.pk).exists()
        assert NaiveRag.all_objects.get(pk=naive_rag.pk).active is False

    def test_link_reached_through_owner_and_target_in_one_call_stays_binned(
        self, python_code_tool, graph
    ):
        # No current delete path reaches one link both ways, so one context
        # deletes the owner's flow and the referenced tool together.
        inline_surface = InlineSurface.objects.create(
            task_node=TaskNode.objects.create(graph=graph, node_name="t")
        )
        tool_link = InlineSurfacePythonTool.objects.create(
            inline_surface=inline_surface, python_tool=python_code_tool, mode=ToolMode.ALLOW
        )
        context = _DeleteContext()

        context.delete(graph)
        context.delete(python_code_tool)
        context.finish()

        assert InlineSurfacePythonTool.all_objects.get(pk=tool_link.pk).soft_delete_batch == context.batch

    def test_every_reference_field_is_a_cascade_foreign_key(self):
        # The reference check runs before the PROTECT/RESTRICT/SET_* rules, so a
        # marked non-CASCADE field would silently bypass them.
        marked = [
            (model, field_name)
            for model in apps.get_models()
            for field_name in getattr(model, "soft_delete_reference_fields", ())
        ]

        assert marked
        for model, field_name in marked:
            field = model._meta.get_field(field_name)
            assert field.many_to_one or field.one_to_one, f"{model._meta.label}.{field_name} is not a FK"
            assert field.remote_field.on_delete is models.CASCADE, f"{model._meta.label}.{field_name}"
