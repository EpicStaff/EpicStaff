"""Tests for the generic, introspection-based soft-delete cascade mechanism
(`tables.services.soft_delete.DeleteService`) and the `SoftDeleteFields` /
`SoftDeleteMixin` base classes it operates on.

Covers, per root and per mechanism rule:
- Full cascade through a multi-level subtree when SOFT_DELETE=True (default).
- Real DB CASCADE hard-delete when SOFT_DELETE=False.
- A model with only `SoftDeleteFields` (no `SoftDeleteMixin`) always hard-deletes
  on a direct `.delete()`, regardless of the flag.
- `Session.graph` is nulled rather than cascaded (nullable-fallback branch).
- Forward-FK targets (`PythonCode`, `DocumentContent`, `GraphRagIndexConfig`)
  are never visited by the reverse-relation walker.
- `ScheduleTriggerNode.is_active` (business field) is untouched by the cascade,
  distinct from `is_soft_deleted` (cascade field) on the same model.
- The PROTECT/RESTRICT/DO_NOTHING guards in `_DeleteContext._process_related_object`.
"""

import json
from unittest.mock import MagicMock

import pytest
from django.db import connection, models
from django.db.models.deletion import ProtectedError, RestrictedError
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from agents.models import InlineSurface, InlineSurfaceKnowledge
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
from tables.models.base_models import SoftDeleteFields
from tables.models.session_models import SessionTrigger
from tables.models.webhook_models import WebhookNodeAuth
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
            assert obj.is_soft_deleted is True
            assert obj.soft_deleted_at is not None

        assert attached_collection.is_soft_deleted is False
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
            assert obj.is_soft_deleted is True
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

        assert python_code_tool.is_soft_deleted is True
        assert python_code_tool.soft_deleted_at is not None
        assert python_code_tool_config.is_soft_deleted is True
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
        assert knowledge_node.is_soft_deleted is True
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
        assert version.is_soft_deleted is True
        assert version.soft_deleted_at is not None


@pytest.mark.django_db
class TestHardDeletePath:
    """Item 2: SOFT_DELETE=False performs a genuine hard delete; real DB
    CASCADE still fires through the subtree exactly as it did before this
    feature existed."""

    @override_settings(SOFT_DELETE=False)
    def test_graph_hard_delete_removes_subtree_but_not_forward_fk_targets(
        self, graph, default_org
    ):
        task_node = TaskNode.objects.create(graph=graph, node_name="task_1")
        inline_surface = InlineSurface.objects.create(task_node=task_node)
        attached_collection = SourceCollection.objects.create(
            org=default_org, collection_name="Attached KB"
        )
        inline_surface_knowledge = InlineSurfaceKnowledge.objects.create(
            inline_surface=inline_surface, collection=attached_collection
        )
        graph_id = graph.id
        task_node_id = task_node.id
        inline_surface_id = inline_surface.id
        inline_surface_knowledge_id = inline_surface_knowledge.id

        graph.delete()

        assert not Graph.all_objects.filter(id=graph_id).exists()
        assert not TaskNode.all_objects.filter(id=task_node_id).exists()
        assert not InlineSurface.all_objects.filter(id=inline_surface_id).exists()
        assert not InlineSurfaceKnowledge.all_objects.filter(
            id=inline_surface_knowledge_id
        ).exists()
        # Forward-FK target: real DB CASCADE never reaches it either.
        assert SourceCollection.all_objects.filter(
            collection_id=attached_collection.collection_id
        ).exists()


@pytest.mark.django_db
class TestDirectDeleteOnGroup2OnlyModel:
    """Item 3: a model with only `SoftDeleteFields` (no `SoftDeleteMixin`)
    always performs a normal hard delete on a direct `.delete()` call, because
    it never overrides `delete()` — regardless of `SOFT_DELETE`."""

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
        assert python_node.is_soft_deleted is True

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
        assert document.is_soft_deleted is True

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
        assert graph_rag.is_soft_deleted is True

        index_config.refresh_from_db()
        assert not isinstance(index_config, SoftDeleteFields)
        assert GraphRagIndexConfig.objects.filter(pk=index_config.pk).exists()


@pytest.mark.django_db
class TestScheduleTriggerNodeIsActiveUntouched:
    """Item 6: `ScheduleTriggerNode.is_active` is its own business field
    (enabled/disabled). It must not collide with the cascade's
    `is_soft_deleted` field on the same model."""

    def test_is_active_business_field_survives_cascade(self, graph):
        node = ScheduleTriggerNode.objects.create(
            graph=graph, node_name="trigger_node", is_active=True
        )

        graph.delete()

        node.refresh_from_db()
        assert node.is_active is True
        assert node.is_soft_deleted is True
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
        assert node.is_soft_deleted is True
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
        node = WebhookTriggerNode.objects.create(
            graph=graph, node_name="trigger_node", python_code=python_code
        )
        # WebhookTriggerNode's post_save signal (tables/signals/webhook_signals.py)
        # auto-creates a WebhookNodeAuth row pointing at this node.
        node_auth = WebhookNodeAuth.objects.get(webhook_trigger_node=node)
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
        assert node.is_soft_deleted is True
        assert node.soft_deleted_at is not None

        trigger.refresh_from_db()
        assert trigger.webhook_trigger_node_id is None

        session.refresh_from_db()
        assert SessionTrigger.objects.filter(pk=trigger.pk).exists()
        assert Session.objects.filter(pk=session.pk).exists()

        # WebhookNodeAuth previously lacked SoftDeleteFields, so this reverse
        # relation fell through to DeleteService's nullable-CASCADE fallback,
        # which tried to null webhook_trigger_node while telegram_trigger_node
        # was also null -- violating the webhook_node_auth_exactly_one_node
        # check constraint with an IntegrityError. Now that WebhookNodeAuth
        # carries SoftDeleteFields, this relation is handled by the batched
        # soft-delete cascade instead: it must soft-delete cleanly and remain
        # queryable via all_objects, with its FK to the node left untouched.
        node_auth.refresh_from_db()
        assert node_auth.is_soft_deleted is True
        assert node_auth.soft_deleted_at is not None
        assert WebhookNodeAuth.all_objects.filter(pk=node_auth.pk).exists()
        assert node_auth.webhook_trigger_node_id == node.pk


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
        assert graph.is_soft_deleted is False
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
        self, graph, redis_client_mock
    ):
        node = ScheduleTriggerNode.objects.create(
            graph=graph, node_name="trigger_node", is_active=True
        )
        # Drop the "create" publish call triggered by objects.create() above,
        # so only the cascade's own publish call is asserted below.
        redis_client_mock.publish.reset_mock()

        graph.delete()

        node.refresh_from_db()
        assert node.is_soft_deleted is True
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
        would require mocking an HTTP client, duplicating
        TestHiddenReverseRelationSetNull's coverage of the same signal's
        side effect via WebhookNodeAuth auto-creation). This test instead
        locks in the outcome that matters for this change: the node is still
        soft-deleted correctly now that it takes the per-object path instead
        of the batched UPDATE."""
        python_code = PythonCode.objects.create(
            code="def main(): return 1", entrypoint="main"
        )
        node = WebhookTriggerNode.objects.create(
            graph=graph, node_name="trigger_node", python_code=python_code
        )

        graph.delete()

        node.refresh_from_db()
        assert node.is_soft_deleted is True
        assert node.soft_deleted_at is not None


@pytest.mark.django_db
class TestBatchedCascadeQueryCountDoesNotGrowWithChildCount:
    """The batched-UPDATE optimization in `_batch_soft_delete_cascade` must
    keep issuing a single UPDATE per model regardless of how many children
    are soft-deleted through it. Compares total query count for a small vs.
    a large batch of plain (no post_save receiver, no M2M or reverse-relation
    descendants of its own) `GraphNote` children of the same `Graph` root —
    no growth confirms the batch path, not one `.save()` per object, is
    still in effect. `TaskNode` is deliberately avoided here: it carries its
    own M2M field (`surface_list`), whose clearing is legitimately done
    per-object regardless of batching, which would make query count grow
    with child count for reasons unrelated to what this test checks."""

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
