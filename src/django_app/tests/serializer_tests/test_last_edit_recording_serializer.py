from datetime import timedelta

import pytest
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from rbac.authorship import (
    LAST_EDIT_TRACKER_CONTEXT_KEY,
    AuthorStampingSerializerMixin,
    LastEditTracker,
    record_last_edit,
)
from rbac.identity.api_keys.principals import SystemServicePrincipal
from rbac.models import LastEditTrackedModel, ResourceLastEdit
from tables.models import Graph, GraphNote, Label
from tables.serializers.model_serializers.graph_serializers import (
    GraphNoteSerializer,
    GraphSerializer,
)

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.user_summary_helpers import expected_user_summary

PREVIOUS_EDIT_AT = timezone.now() - timedelta(days=1)


class GraphNoteWriteSerializer(AuthorStampingSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = GraphNote
        fields = ["id", "graph", "content", "metadata", "created_by"]


class GraphNoteBodySuperSerializer(GraphNoteWriteSerializer):
    def create(self, validated_data):
        return super().create(validated_data)

    def update(self, instance, validated_data):
        return super().update(instance, validated_data)


class GraphNoteBodySuperChildSerializer(GraphNoteBodySuperSerializer):
    def create(self, validated_data):
        return super().create(validated_data)

    def update(self, instance, validated_data):
        return super().update(instance, validated_data)


class LabelWriteSerializer(AuthorStampingSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = Label
        fields = ["id", "name", "org", "created_by"]


LAYOUTS = [
    GraphNoteWriteSerializer,
    GraphNoteBodySuperSerializer,
    GraphNoteBodySuperChildSerializer,
]
LAYOUT_IDS = ["mixin-only", "body-super", "body-super-child"]


@pytest.fixture
def editor(db, django_user_model):
    return django_user_model.objects.create_user(
        email="serializer-editor@example.com", password="StrongPass123!"
    )


@pytest.fixture
def previous_editor(db, django_user_model):
    return django_user_model.objects.create_user(
        email="serializer-previous-editor@example.com", password="StrongPass123!"
    )


@pytest.fixture
def acme_graph(acme):
    return Graph.objects.create(name="serializer-last-edit-flow", org=acme)


@pytest.fixture
def note(acme_graph, previous_editor):
    note = GraphNote.objects.create(
        graph=acme_graph, content="note", metadata={"position": {"x": 1, "y": 1}, "color": "#fff"}
    )
    record_last_edit(note, previous_editor, edited_at=PREVIOUS_EDIT_AT)
    return note


def _context_for(user):
    request = Request(APIRequestFactory().post("/"))
    request.user = user
    return {"request": request}


def _last_edit_of(instance) -> ResourceLastEdit | None:
    return ResourceLastEdit.objects.filter(
        content_type=ContentType.objects.get_for_model(instance), object_id=instance.pk
    ).first()


def _last_edit_upserts(captured) -> int:
    return sum(
        'INSERT INTO "rbac_resourcelastedit"' in query["sql"] for query in captured.captured_queries
    )


@pytest.mark.django_db
@pytest.mark.parametrize("serializer_class", LAYOUTS, ids=LAYOUT_IDS)
def test_create_records_creator_once(serializer_class, acme_graph, editor):
    serializer = serializer_class(
        data={"graph": acme_graph.id, "content": "new", "metadata": {}},
        context=_context_for(editor),
    )
    serializer.is_valid(raise_exception=True)

    with CaptureQueriesContext(connection) as captured:
        created = serializer.save()

    assert _last_edit_upserts(captured) == 1
    assert _last_edit_of(created).edited_by_id == editor.id


@pytest.mark.django_db
@pytest.mark.parametrize("serializer_class", LAYOUTS, ids=LAYOUT_IDS)
def test_update_that_changes_content_records_editor_once(serializer_class, note, editor):
    serializer = serializer_class(
        note, data={"content": "edited"}, partial=True, context=_context_for(editor)
    )
    serializer.is_valid(raise_exception=True)

    with CaptureQueriesContext(connection) as captured:
        serializer.save()

    assert _last_edit_upserts(captured) == 1
    last_edit = _last_edit_of(note)
    assert last_edit.edited_by_id == editor.id
    assert last_edit.edited_at > PREVIOUS_EDIT_AT


@pytest.mark.django_db
@pytest.mark.parametrize("serializer_class", LAYOUTS, ids=LAYOUT_IDS)
def test_update_that_changes_nothing_records_nothing(
    serializer_class, note, editor, previous_editor
):
    serializer = serializer_class(
        note,
        data={"content": "note", "metadata": {"position": {"x": 1, "y": 1}, "color": "#fff"}},
        partial=True,
        context=_context_for(editor),
    )
    serializer.is_valid(raise_exception=True)

    serializer.save()

    last_edit = _last_edit_of(note)
    assert last_edit.edited_by_id == previous_editor.id
    assert last_edit.edited_at == PREVIOUS_EDIT_AT


@pytest.mark.django_db
def test_node_metadata_only_update_is_not_an_edit(note, editor, previous_editor):
    serializer = GraphNoteWriteSerializer(
        note,
        data={"metadata": {"position": {"x": 99, "y": 1}, "color": "#fff"}},
        partial=True,
        context=_context_for(editor),
    )
    serializer.is_valid(raise_exception=True)

    serializer.save()

    assert GraphNote.objects.get(pk=note.pk).metadata["position"] == {"x": 99, "y": 1}
    assert _last_edit_of(note).edited_by_id == previous_editor.id


@pytest.mark.django_db
def test_direct_update_call_records_editor(note, editor):
    serializer = GraphNoteWriteSerializer(context=_context_for(editor))

    serializer.update(note, {"content": "direct"})

    assert _last_edit_of(note).edited_by_id == editor.id


@pytest.mark.django_db
def test_system_principal_records_time_without_editor(acme_graph):
    serializer = GraphNoteWriteSerializer(
        data={"graph": acme_graph.id, "content": "system", "metadata": {}},
        context=_context_for(SystemServicePrincipal()),
    )
    serializer.is_valid(raise_exception=True)

    created = serializer.save()

    last_edit = _last_edit_of(created)
    assert last_edit.edited_by_id is None
    assert last_edit.edited_at is not None


@pytest.mark.django_db
def test_write_without_request_uses_explicit_author(acme_graph, editor):
    serializer = GraphNoteWriteSerializer(
        data={"graph": acme_graph.id, "content": "explicit", "metadata": {}}
    )
    serializer.is_valid(raise_exception=True)

    created = serializer.save(created_by=editor)

    assert _last_edit_of(created).edited_by_id == editor.id


@pytest.mark.django_db
def test_write_without_any_acting_user_records_nothing(acme_graph):
    serializer = GraphNoteWriteSerializer(
        data={"graph": acme_graph.id, "content": "anonymous", "metadata": {}}
    )
    serializer.is_valid(raise_exception=True)

    created = serializer.save()

    assert _last_edit_of(created) is None


@pytest.mark.django_db
def test_untracked_model_records_nothing(acme, editor):
    serializer = LabelWriteSerializer(
        data={"name": "untracked", "org": acme.id}, context=_context_for(editor)
    )
    serializer.is_valid(raise_exception=True)

    serializer.save()

    assert not ResourceLastEdit.objects.exists()


@pytest.mark.django_db
def test_shared_tracker_records_only_on_finish(note, editor):
    tracker = LastEditTracker(editor)
    context = {**_context_for(editor), LAST_EDIT_TRACKER_CONTEXT_KEY: tracker}
    serializer = GraphNoteWriteSerializer(
        note, data={"content": "tracked"}, partial=True, context=context
    )
    serializer.is_valid(raise_exception=True)
    serializer.save()
    # A write made outside the serializer before finish() is part of the comparison.
    GraphNote.objects.filter(pk=note.pk).update(content="changed-later")

    assert _last_edit_of(note).edited_at == PREVIOUS_EDIT_AT
    tracker.finish()

    assert _last_edit_of(note).edited_by_id == editor.id
    assert _last_edit_of(note.graph).edited_by_id == editor.id


def _finish_metadata_write(note, editor, metadata):
    tracker = LastEditTracker(editor)
    context = {**_context_for(editor), LAST_EDIT_TRACKER_CONTEXT_KEY: tracker}
    serializer = GraphNoteWriteSerializer(
        note, data={"metadata": metadata}, partial=True, context=context
    )
    serializer.is_valid(raise_exception=True)
    serializer.save()
    tracker.finish()


@pytest.mark.django_db
def test_position_change_is_owner_edit_only(note, editor, previous_editor):
    _finish_metadata_write(note, editor, {"position": {"x": 5, "y": 5}, "color": "#000"})

    assert _last_edit_of(note).edited_by_id == previous_editor.id
    assert _last_edit_of(note.graph).edited_by_id == editor.id


@pytest.mark.django_db
def test_appearance_change_is_no_edit_at_all(note, editor, previous_editor):
    _finish_metadata_write(
        note, editor, {"position": {"x": 1, "y": 1}, "color": "#000", "size": {"width": 9}}
    )

    assert _last_edit_of(note).edited_by_id == previous_editor.id
    assert _last_edit_of(note.graph) is None


def _last_edit_reads(captured) -> int:
    return sum(
        'FROM "rbac_resourcelastedit"' in query["sql"] for query in captured.captured_queries
    )


@pytest.mark.django_db
def test_unprefetched_render_reads_last_edit_once(note, previous_editor):
    note = GraphNote.objects.get(pk=note.pk)

    with CaptureQueriesContext(connection) as captured:
        data = GraphNoteSerializer(note).data

    assert _last_edit_reads(captured) == 1
    assert data["last_edited_by"] == expected_user_summary(previous_editor)
    assert data["last_edited_at"] is not None


@pytest.mark.django_db
def test_list_render_never_mixes_rows(acme_graph, editor, previous_editor):
    first = GraphNote.objects.create(graph=acme_graph, content="first")
    second = GraphNote.objects.create(graph=acme_graph, content="second")
    record_last_edit(first, editor)
    record_last_edit(second, previous_editor)

    data = GraphNoteSerializer([first, second], many=True).data

    assert [row["last_edited_by"] for row in data] == [
        expected_user_summary(editor),
        expected_user_summary(previous_editor),
    ]


@pytest.mark.django_db
def test_change_detection_does_not_read_last_edits(note, editor):
    serializer = GraphNoteSerializer(
        note, data={"content": "edited"}, partial=True, context=_context_for(editor)
    )
    serializer.is_valid(raise_exception=True)

    with CaptureQueriesContext(connection) as captured:
        serializer.save()

    assert _last_edit_reads(captured) == 0
    assert _last_edit_upserts(captured) == 1


def test_graph_prefetch_lookups_cover_every_tracked_graph_relation():
    # Every tracked model hanging off Graph.graph is a node list the graph detail
    # renders; a new one without a prefetch would query once per row.
    tracked_node_relations = {
        relation.get_accessor_name()
        for relation in Graph._meta.related_objects
        if relation.field.name == "graph"
        and issubclass(relation.related_model, LastEditTrackedModel)
    }

    lookups = {
        prefetch.prefetch_through for prefetch in GraphSerializer.authorship_prefetch_lookups()
    }

    assert len(tracked_node_relations) == 16
    assert {f"{relation}__last_edits" for relation in tracked_node_relations} <= lookups
    assert {f"{relation}__created_by" for relation in tracked_node_relations} <= lookups
    # The graph renders its own author and last edit, and those of each subflow.
    assert {
        "last_edits",
        "created_by",
        "subgraph_node_list__subgraph__last_edits",
        "subgraph_node_list__subgraph__created_by",
    } <= lookups


@pytest.mark.django_db
def test_graph_prefetch_lookups_render_node_authorship_without_queries(
    acme_graph, editor, previous_editor
):
    authored = GraphNote.objects.create(graph=acme_graph, content="note", created_by=editor)
    record_last_edit(authored, previous_editor)
    graph = Graph.objects.prefetch_related(*GraphSerializer.authorship_prefetch_lookups()).get(
        pk=acme_graph.pk
    )

    with CaptureQueriesContext(connection) as captured:
        rendered_note = GraphNoteSerializer(graph.graph_note_list.all()[0]).data

    assert captured.captured_queries == []
    assert rendered_note["created_by"] == expected_user_summary(editor)
    assert rendered_note["last_edited_by"] == expected_user_summary(previous_editor)


# ---- change detection keeps reading ids, never users ----


def _user_reads(captured) -> int:
    return sum('FROM "rbac_user"' in query["sql"] for query in captured.captured_queries)


@pytest.mark.django_db
def test_no_op_update_of_authored_resource_records_nothing(acme_graph, editor, previous_editor):
    authored = GraphNote.objects.create(
        graph=acme_graph, content="note", created_by=previous_editor
    )
    record_last_edit(authored, previous_editor, edited_at=PREVIOUS_EDIT_AT)
    authored = GraphNote.objects.get(pk=authored.pk)
    serializer = GraphNoteSerializer(
        authored, data={"content": "note"}, partial=True, context=_context_for(editor)
    )
    serializer.is_valid(raise_exception=True)

    with CaptureQueriesContext(connection) as captured:
        serializer.save()

    assert _last_edit_upserts(captured) == 0
    assert _user_reads(captured) == 0
    assert _last_edit_of(authored).edited_by_id == previous_editor.id


@pytest.mark.django_db
def test_tracker_compares_authored_state_without_reading_users(acme_graph, editor, previous_editor):
    authored = GraphNote.objects.create(
        graph=acme_graph, content="note", created_by=previous_editor
    )
    authored = GraphNote.objects.get(pk=authored.pk)
    tracker = LastEditTracker(editor)
    tracker.watch_update(GraphNoteSerializer(context=_context_for(editor)), authored)
    GraphNote.objects.filter(pk=authored.pk).update(content="edited elsewhere")

    with CaptureQueriesContext(connection) as captured:
        tracker.finish()

    assert _user_reads(captured) == 0
    assert _last_edit_upserts(captured) == 1
    assert _last_edit_of(authored).edited_by_id == editor.id
