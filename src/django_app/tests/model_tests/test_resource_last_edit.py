from datetime import timedelta

import pytest
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from agents.models import AgentDefinition
from rbac.authorship import record_last_edit, record_last_edits
from rbac.authorship.registry import last_edit_tracked_models
from rbac.identity.api_keys.principals import SystemServicePrincipal
from rbac.models import LastEditTrackedModel, ResourceLastEdit
from tables.models import Graph, GraphNote, Label, StorageFile
from tables.models.graph_models import Edge, PythonNode, StartNode
from tables.models.knowledge_models import SourceCollection
from tables.models.python_models import PythonCode, PythonCodeTool

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.fixture
def editor(db, django_user_model):
    return django_user_model.objects.create_user(
        email="last-editor@example.com", password="StrongPass123!"
    )


@pytest.fixture
def other_editor(db, django_user_model):
    return django_user_model.objects.create_user(
        email="other-last-editor@example.com", password="StrongPass123!"
    )


@pytest.fixture
def acme_graph(acme):
    return Graph.objects.create(name="last-edit-flow", org=acme)


def _last_edit_of(instance) -> ResourceLastEdit:
    return ResourceLastEdit.objects.get(
        content_type=ContentType.objects.get_for_model(instance), object_id=instance.pk
    )


@pytest.mark.django_db
def test_first_record_inserts_row(acme_graph, editor):
    edited_at = timezone.now()

    record_last_edit(acme_graph, editor, edited_at=edited_at)

    last_edit = _last_edit_of(acme_graph)
    assert last_edit.edited_by_id == editor.id
    assert last_edit.edited_at == edited_at


@pytest.mark.django_db
def test_record_defaults_edited_at_to_now(acme_graph, editor):
    before = timezone.now()

    record_last_edit(acme_graph, editor)

    assert before <= _last_edit_of(acme_graph).edited_at <= timezone.now()


@pytest.mark.django_db
def test_same_user_again_keeps_row_and_moves_time(acme_graph, editor):
    first_time = timezone.now() - timedelta(hours=1)
    record_last_edit(acme_graph, editor, edited_at=first_time)
    first_row = _last_edit_of(acme_graph)

    record_last_edit(acme_graph, editor)

    second_row = _last_edit_of(acme_graph)
    assert second_row.pk == first_row.pk
    assert second_row.edited_by_id == editor.id
    assert second_row.edited_at > first_time


@pytest.mark.django_db
def test_other_user_replaces_editor_on_same_row(acme_graph, editor, other_editor):
    first_time = timezone.now() - timedelta(hours=1)
    record_last_edit(acme_graph, editor, edited_at=first_time)
    first_row = _last_edit_of(acme_graph)

    record_last_edit(acme_graph, other_editor)

    second_row = _last_edit_of(acme_graph)
    assert second_row.pk == first_row.pk
    assert second_row.edited_by_id == other_editor.id
    assert second_row.edited_at > first_time
    assert ResourceLastEdit.objects.count() == 1


@pytest.mark.django_db
def test_system_principal_records_time_without_editor(acme_graph, editor):
    record_last_edit(acme_graph, editor, edited_at=timezone.now() - timedelta(hours=1))
    before = timezone.now()

    record_last_edit(acme_graph, SystemServicePrincipal())

    last_edit = _last_edit_of(acme_graph)
    assert last_edit.edited_by_id is None
    assert last_edit.edited_at >= before


@pytest.mark.django_db
def test_batch_record_is_one_statement(acme, acme_graph, editor):
    notes = [
        GraphNote.objects.create(graph=acme_graph, content=f"note-{index}") for index in range(3)
    ]
    record_last_edit(notes[0], editor)
    instances = [acme_graph, *notes]
    for instance in instances:
        ContentType.objects.get_for_model(instance)

    with CaptureQueriesContext(connection) as captured:
        record_last_edits(instances, editor)

    assert len(captured.captured_queries) == 1
    assert "ON CONFLICT" in captured.captured_queries[0]["sql"]
    assert {_last_edit_of(instance).edited_by_id for instance in instances} == {editor.id}


@pytest.mark.django_db
def test_batch_record_accepts_same_instance_twice(acme_graph, editor):
    record_last_edits([acme_graph, acme_graph], editor)

    assert _last_edit_of(acme_graph).edited_by_id == editor.id


@pytest.mark.django_db
def test_batch_record_without_instances_issues_no_query(editor):
    with CaptureQueriesContext(connection) as captured:
        record_last_edits([], editor)

    assert captured.captured_queries == []


@pytest.mark.django_db
def test_deleting_resource_deletes_its_last_edit(acme, editor):
    definition = AgentDefinition.objects.create(org=acme, name="agent-with-last-edit")
    record_last_edit(definition, editor)

    definition.delete()

    assert not ResourceLastEdit.objects.exists()


@pytest.mark.django_db
def test_deleting_graph_deletes_last_edits_of_its_nodes(acme_graph, python_code, editor):
    note = GraphNote.objects.create(graph=acme_graph, content="note")
    python_node = PythonNode.objects.create(graph=acme_graph, python_code=python_code)
    start_node = StartNode.objects.create(graph=acme_graph, variables={})
    record_last_edits([acme_graph, note, python_node, start_node], editor)

    Graph.all_objects.filter(pk=acme_graph.pk).delete()

    assert not ResourceLastEdit.objects.exists()


@pytest.mark.django_db
def test_deleting_editor_keeps_last_edit_time(acme_graph, editor):
    edited_at = timezone.now()
    record_last_edit(acme_graph, editor, edited_at=edited_at)

    editor.delete()

    last_edit = _last_edit_of(acme_graph)
    assert last_edit.edited_by_id is None
    assert last_edit.edited_at == edited_at


@pytest.mark.django_db
def test_last_edits_relation_reads_the_row(acme_graph, editor):
    record_last_edit(acme_graph, editor)

    graph = Graph.objects.prefetch_related("last_edits").get(pk=acme_graph.pk)

    assert [last_edit.edited_by_id for last_edit in graph.last_edits.all()] == [editor.id]


EXPECTED_TRACKED_MODEL_NAMES = {
    "Graph",
    "PythonNode",
    "KnowledgeNode",
    "FileExtractorNode",
    "KeyValueNode",
    "AudioTranscriptionNode",
    "EndNode",
    "SubGraphNode",
    "StartNode",
    "DecisionTableNode",
    "WebhookTriggerNode",
    "TelegramTriggerNode",
    "ScheduleTriggerNode",
    "ClassificationDecisionTableNode",
    "GraphNote",
    "TaskNode",
    "AgentNode",
    "PythonCodeTool",
    "McpTool",
    "LLMConfig",
    "EmbeddingConfig",
    "RealtimeChannel",
    "WebhookTrigger",
    "AgentDefinition",
    "Surface",
    "StorageFile",
    "SourceCollection",
}


def test_registry_lists_exactly_the_tracked_models():
    tracked = dict(last_edit_tracked_models())

    assert {model.__name__ for model in tracked} == EXPECTED_TRACKED_MODEL_NAMES
    assert tracked[GraphNote] == "graph__org_id"
    assert tracked[Graph] == "org_id"
    assert tracked[StorageFile] == "org_id"
    assert tracked[SourceCollection] == "org_id"
    assert not issubclass(Label, LastEditTrackedModel)


def test_only_node_position_in_canvas_metadata_is_a_graph_edit():
    assert GraphNote.last_edit_canvas_fields == {"metadata": ("position",)}
    assert Edge.last_edit_canvas_fields == {"metadata": ("position",)}
    assert not hasattr(Graph, "last_edit_canvas_fields")


@pytest.mark.django_db
def test_built_in_tool_is_never_recorded(acme, editor):
    code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    built_in = PythonCodeTool.objects.create(
        name="shared-tool", description="", python_code=code, built_in=True
    )
    custom = PythonCodeTool.objects.create(
        name="own-tool", description="", python_code=code, org=acme
    )

    record_last_edits([built_in, custom], editor)

    assert not ResourceLastEdit.objects.filter(object_id=built_in.pk).exists()
    assert _last_edit_of(custom).edited_by_id == editor.id
