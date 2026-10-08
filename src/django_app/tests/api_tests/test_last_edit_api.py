import json
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from agents.models import AgentDefinition
from rbac.authorship import record_last_edit, record_last_edits
from rbac.identity.api_keys.principals import SystemServicePrincipal
from rbac.models import Organization, OrganizationUser, ResourceLastEdit
from tables.models import (
    ElevenLabsRealtimeConfig,
    EmbeddingConfig,
    GeminiRealtimeConfig,
    Graph,
    GraphNote,
    KeyValueTable,
    Label,
    OpenAIRealtimeConfig,
    RealtimeChannel,
    StorageFile,
    WebhookTrigger,
)
from tables.models.graph_models import ConditionGroup, DecisionTableNode, Edge, PythonNode
from tables.models.knowledge_models import SourceCollection
from tables.models.llm_models import LLMConfig
from tables.models.python_models import PythonCode, PythonCodeTool
from tests.fixtures import *  # noqa: F401,F403
from tests.user_summary_helpers import expected_user_summary

PREVIOUS_EDIT_AT = timezone.now() - timedelta(days=1)


@pytest.fixture
def colleague(db, default_org, org_admin_role):
    user = get_user_model().objects.create_user(
        email="last-edit-colleague@example.com", password="ColleagueStrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=default_org, role=org_admin_role)
    return user


@pytest.fixture
def colleague_client(colleague, default_org) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=colleague)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(default_org.id))
    return client


@pytest.fixture
def outsider_client(db, org_admin_role) -> APIClient:
    other_org = Organization.objects.create(name="last-edit-other-org")
    outsider = get_user_model().objects.create_user(
        email="last-edit-outsider@example.com", password="OutsiderStrongPass123!"
    )
    OrganizationUser.objects.create(user=outsider, org=other_org, role=org_admin_role)
    client = APIClient()
    client.force_authenticate(user=outsider)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(other_org.id))
    return client


@pytest.fixture
def note(graph, regular_user) -> GraphNote:
    note = GraphNote.objects.create(graph=graph, content="note", metadata={"x": 1})
    record_last_edit(note, regular_user, edited_at=PREVIOUS_EDIT_AT)
    return note


def _last_edit_of(instance) -> ResourceLastEdit | None:
    return ResourceLastEdit.objects.filter(
        content_type=ContentType.objects.get_for_model(instance), object_id=instance.pk
    ).first()


def _assert_fields_show(data: dict, user) -> None:
    assert data["last_edited_by"] == expected_user_summary(user)
    assert data["last_edited_at"] is not None


# ---- REST create / update ----


@pytest.mark.django_db
def test_create_records_creator_and_returns_last_edit(auth_client, regular_user, graph):
    response = auth_client.post(
        reverse("graphnote-list"),
        {"graph": graph.id, "content": "hello", "metadata": {}},
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    last_edit = _last_edit_of(GraphNote.objects.get(pk=response.data["id"]))
    assert last_edit.edited_by_id == regular_user.id
    assert timezone.now() - last_edit.edited_at < timedelta(minutes=1)
    _assert_fields_show(response.data, regular_user)


@pytest.mark.django_db
def test_patch_by_other_user_replaces_last_edit(colleague_client, colleague, note):
    response = colleague_client.patch(
        reverse("graphnote-detail", args=[note.pk]), {"content": "edited"}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    last_edit = _last_edit_of(note)
    assert last_edit.edited_by_id == colleague.id
    assert last_edit.edited_at > PREVIOUS_EDIT_AT
    _assert_fields_show(response.data, colleague)


@pytest.mark.django_db
def test_patch_that_changes_nothing_records_nothing(colleague_client, regular_user, note):
    response = colleague_client.patch(
        reverse("graphnote-detail", args=[note.pk]),
        {"content": "note", "metadata": {"x": 1}},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    last_edit = _last_edit_of(note)
    assert last_edit.edited_by_id == regular_user.id
    assert last_edit.edited_at == PREVIOUS_EDIT_AT


@pytest.mark.django_db
def test_patch_moving_node_is_not_an_edit(colleague_client, regular_user, note):
    response = colleague_client.patch(
        reverse("graphnote-detail", args=[note.pk]), {"metadata": {"x": 300}}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert _last_edit_of(note).edited_by_id == regular_user.id


@pytest.mark.django_db
def test_patch_of_json_key_named_id_is_an_edit(colleague_client, colleague, graph, python_code):
    node = PythonNode.objects.create(
        graph=graph, python_code=python_code, node_name="py", input_map={"id": "a"}
    )
    record_last_edit(node, SystemServicePrincipal(), edited_at=PREVIOUS_EDIT_AT)

    response = colleague_client.patch(
        reverse("pythonnode-detail", args=[node.pk]), {"input_map": {"id": "b"}}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert _last_edit_of(node).edited_by_id == colleague.id


@pytest.mark.django_db
def test_patch_from_other_org_is_404_and_records_nothing(outsider_client, regular_user, note):
    response = outsider_client.patch(
        reverse("graphnote-detail", args=[note.pk]), {"content": "hijack"}, format="json"
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    last_edit = _last_edit_of(note)
    assert last_edit.edited_by_id == regular_user.id
    assert last_edit.edited_at == PREVIOUS_EDIT_AT


@pytest.mark.django_db
def test_graph_patch_records_editor_only_when_changed(
    colleague_client, colleague, regular_user, graph
):
    record_last_edit(graph, regular_user, edited_at=PREVIOUS_EDIT_AT)
    url = reverse("graphs-detail", args=[graph.pk])

    unchanged = colleague_client.patch(
        url, {"name": graph.name, "save_version": graph.save_version}, format="json"
    )
    assert unchanged.status_code == status.HTTP_200_OK, unchanged.content
    assert _last_edit_of(graph).edited_by_id == regular_user.id

    graph.refresh_from_db()
    renamed = colleague_client.patch(
        url, {"name": "renamed", "save_version": graph.save_version}, format="json"
    )
    assert renamed.status_code == status.HTTP_200_OK, renamed.content
    assert _last_edit_of(graph).edited_by_id == colleague.id
    _assert_fields_show(renamed.data, colleague)


# ---- decision table: condition groups are written outside the serializer ----


@pytest.fixture
def decision_table(graph, regular_user) -> DecisionTableNode:
    node = DecisionTableNode.objects.create(graph=graph, node_name="decide")
    ConditionGroup.objects.create(
        decision_table_node=node, group_name="g1", group_type="simple", order=0
    )
    record_last_edit(node, regular_user, edited_at=PREVIOUS_EDIT_AT)
    return node


def _group_payload(expression: str | None) -> list[dict]:
    return [{"group_name": "g1", "group_type": "simple", "order": 0, "expression": expression}]


@pytest.mark.django_db
def test_decision_table_groups_change_is_edit(colleague_client, colleague, decision_table):
    response = colleague_client.patch(
        reverse("decisiontablenode-detail", args=[decision_table.pk]),
        {"condition_groups": _group_payload("a > 1")},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert _last_edit_of(decision_table).edited_by_id == colleague.id
    _assert_fields_show(response.data, colleague)


@pytest.mark.django_db
def test_decision_table_same_groups_recreated_is_not_edit(
    colleague_client, regular_user, decision_table
):
    response = colleague_client.patch(
        reverse("decisiontablenode-detail", args=[decision_table.pk]),
        {"condition_groups": _group_payload(None)},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert _last_edit_of(decision_table).edited_by_id == regular_user.id


@pytest.mark.django_db
def test_classification_decision_table_create_records_creator(auth_client, regular_user, graph):
    response = auth_client.post(
        reverse("classificationdecisiontablenode-list"),
        {"graph": graph.id, "node_name": "classify"},
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    _assert_fields_show(response.data, regular_user)


# ---- read endpoints carry the fields ----


@pytest.mark.django_db
def test_node_list_and_detail_carry_last_edit(auth_client, regular_user, note):
    listed = auth_client.get(reverse("graphnote-list"))
    detail = auth_client.get(reverse("graphnote-detail", args=[note.pk]))

    assert listed.status_code == status.HTTP_200_OK
    listed_notes = listed.data["results"] if "results" in listed.data else listed.data
    _assert_fields_show(next(item for item in listed_notes if item["id"] == note.pk), regular_user)
    _assert_fields_show(detail.data, regular_user)


@pytest.mark.django_db
def test_graph_detail_and_lists_carry_last_edit(auth_client, regular_user, graph, note):
    record_last_edit(graph, regular_user)

    detail = auth_client.get(reverse("graphs-detail", args=[graph.pk]))
    light = auth_client.get(reverse("graphs-light-list"))

    assert detail.status_code == status.HTTP_200_OK, detail.content
    _assert_fields_show(detail.data, regular_user)
    _assert_fields_show(detail.data["graph_note_list"][0], regular_user)
    light_graphs = light.data["results"] if "results" in light.data else light.data
    _assert_fields_show(next(item for item in light_graphs if item["id"] == graph.pk), regular_user)


@pytest.mark.django_db
def test_python_code_tool_create_and_detail_carry_last_edit(auth_client, regular_user):
    created = auth_client.post(
        reverse("pythoncodetool-list"),
        {
            "name": "last-edit-tool",
            "description": "tool",
            "python_code": {"code": "def main(): return 1", "entrypoint": "main", "libraries": []},
        },
        format="json",
    )
    assert created.status_code == status.HTTP_201_CREATED, created.content
    _assert_fields_show(created.data, regular_user)

    detail = auth_client.get(reverse("pythoncodetool-detail", args=[created.data["id"]]))

    _assert_fields_show(detail.data, regular_user)


@pytest.mark.django_db
def test_python_code_tool_patch_without_change_records_nothing(
    colleague_client, regular_user, default_org
):
    tool = PythonCodeTool.objects.create(
        name="unchanged-tool",
        description="tool",
        org=default_org,
        python_code=PythonCode.objects.create(code="def main(): return 1", entrypoint="main"),
    )
    record_last_edit(tool, regular_user, edited_at=PREVIOUS_EDIT_AT)

    response = colleague_client.patch(
        reverse("pythoncodetool-detail", args=[tool.pk]), {"description": "tool"}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert _last_edit_of(tool).edited_by_id == regular_user.id


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("basename", "model", "name_field"),
    [
        ("embeddingconfig", EmbeddingConfig, "custom_name"),
        ("openairealtimeconfig", OpenAIRealtimeConfig, "custom_name"),
        ("elevenlabsrealtimeconfig", ElevenLabsRealtimeConfig, "custom_name"),
        ("geminirealtimeconfig", GeminiRealtimeConfig, "custom_name"),
        ("realtimechannel", RealtimeChannel, "name"),
        ("webhooktrigger", WebhookTrigger, "path"),
        ("agentdefinition", AgentDefinition, "name"),
        ("key-value-tables", KeyValueTable, "name"),
    ],
    ids=[
        "embedding-config",
        "openai-realtime-config",
        "elevenlabs-realtime-config",
        "gemini-realtime-config",
        "realtime-channel",
        "webhook-trigger",
        "agent-definition",
        "key-value-table",
    ],
)
def test_patch_resending_unchanged_values_and_created_at_records_nothing(
    colleague_client, regular_user, default_org, basename, model, name_field
):
    row = model.objects.create(org=default_org, **{name_field: "unchanged-row"})
    record_last_edit(row, regular_user, edited_at=PREVIOUS_EDIT_AT)

    response = colleague_client.patch(
        reverse(f"{basename}-detail", args=[row.pk]),
        {name_field: "unchanged-row", "created_at": "2001-01-01T00:00:00Z"},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert ResourceLastEdit.objects.count() == 1
    last_edit = _last_edit_of(row)
    assert last_edit.edited_by_id == regular_user.id
    assert last_edit.edited_at == PREVIOUS_EDIT_AT


@pytest.mark.django_db
def test_label_change_on_built_in_tool_records_nothing(auth_client, default_org):
    tool = PythonCodeTool.objects.create(
        name="built-in-tool",
        description="shared",
        built_in=True,
        python_code=PythonCode.objects.create(code="def main(): return 1", entrypoint="main"),
    )
    label = Label.objects.create(name="mine", org=default_org, scope=Label.Scope.TOOL)

    response = auth_client.patch(
        reverse("pythoncodetool-detail", args=[tool.pk]), {"labels": [label.id]}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["labels"] == [label.id]
    assert _last_edit_of(tool) is None
    assert response.data["last_edited_by"] is None


@pytest.mark.django_db
def test_agent_definition_create_patch_and_list_carry_last_edit(
    auth_client, colleague_client, regular_user, colleague
):
    created = auth_client.post(
        reverse("agentdefinition-list"), {"name": "last-edit-agent"}, format="json"
    )
    assert created.status_code == status.HTTP_201_CREATED, created.content
    _assert_fields_show(created.data, regular_user)
    definition = AgentDefinition.objects.get(pk=created.data["id"])

    unchanged = colleague_client.patch(
        reverse("agentdefinition-detail", args=[definition.pk]),
        {"name": "last-edit-agent"},
        format="json",
    )
    assert unchanged.status_code == status.HTTP_200_OK, unchanged.content
    assert unchanged.data["last_edited_by"] == expected_user_summary(regular_user)

    edited = colleague_client.patch(
        reverse("agentdefinition-detail", args=[definition.pk]),
        {"description": "now described"},
        format="json",
    )
    assert edited.status_code == status.HTTP_200_OK, edited.content
    _assert_fields_show(edited.data, colleague)

    listed = auth_client.get(reverse("agentdefinition-list"))
    listed_definitions = listed.data["results"] if "results" in listed.data else listed.data
    _assert_fields_show(
        next(item for item in listed_definitions if item["id"] == definition.pk), colleague
    )


@pytest.mark.django_db
def test_storage_files_listing_carries_last_edit(auth_client, regular_user, default_org):
    storage_file = StorageFile.objects.create(org=default_org, path="docs/a.txt", name="a.txt")
    record_last_edit(storage_file, regular_user)

    response = auth_client.get(reverse("storage-files-by-ids"), {"ids": str(storage_file.id)})

    assert response.status_code == status.HTTP_200_OK, response.content
    _assert_fields_show(response.data[0], regular_user)


@pytest.mark.django_db
def test_collection_list_and_detail_carry_last_edit(auth_client, regular_user, default_org):
    collection = SourceCollection.objects.create(collection_name="docs", org=default_org)
    record_last_edit(collection, regular_user)

    listed = auth_client.get(reverse("sourcecollection-list"))
    detail = auth_client.get(reverse("sourcecollection-detail", args=[collection.pk]))

    assert listed.status_code == status.HTTP_200_OK, listed.content
    listed_collections = listed.data["results"] if "results" in listed.data else listed.data
    _assert_fields_show(
        next(item for item in listed_collections if item["collection_id"] == collection.pk),
        regular_user,
    )
    _assert_fields_show(detail.data, regular_user)


@pytest.mark.django_db
def test_resource_without_last_edit_returns_nulls(auth_client, graph):
    note = GraphNote.objects.create(graph=graph, content="never recorded")

    response = auth_client.get(reverse("graphnote-detail", args=[note.pk]))

    assert response.data["last_edited_by"] is None
    assert response.data["last_edited_at"] is None


# ---- query counts do not grow with rows ----


def _captured_sql(client, url) -> list[str]:
    with CaptureQueriesContext(connection) as captured:
        response = client.get(url)
    assert response.status_code == status.HTTP_200_OK, response.content
    return [query["sql"] for query in captured.captured_queries]


def _count_queries(client, url) -> int:
    return len(_captured_sql(client, url))


def _add_edited_nodes(graph, python_code, users: list, count: int) -> None:
    for index in range(count):
        author = users[index % len(users)]
        editor = users[(index + 1) % len(users)]
        note = GraphNote.objects.create(graph=graph, content=f"note-{index}", created_by=author)
        python_node = PythonNode.objects.create(
            graph=graph,
            python_code=PythonCode.objects.create(code=python_code.code, entrypoint="main"),
            node_name=f"py-{index}",
            created_by=author,
        )
        record_last_edits([note, python_node], editor)


@pytest.mark.django_db
def test_graph_detail_query_count_does_not_grow_with_nodes(
    auth_client, regular_user, colleague, default_org, python_code
):
    users = [regular_user, colleague]
    small = Graph.objects.create(name="small-flow", org=default_org)
    large = Graph.objects.create(name="large-flow", org=default_org)
    _add_edited_nodes(small, python_code, users, 1)
    _add_edited_nodes(large, python_code, users, 3)
    record_last_edit(small, regular_user)
    record_last_edit(large, colleague)
    _count_queries(auth_client, reverse("graphs-detail", args=[small.pk]))

    small_sql = _captured_sql(auth_client, reverse("graphs-detail", args=[small.pk]))
    large_sql = _captured_sql(auth_client, reverse("graphs-detail", args=[large.pk]))

    assert len(large_sql) == len(small_sql)
    assert _user_query_count(large_sql) == _user_query_count(small_sql)


def _user_query_count(captured_sql: list[str]) -> int:
    return sum('FROM "rbac_user"' in sql for sql in captured_sql)


def _count_last_edit_queries(client, url) -> int:
    with CaptureQueriesContext(connection) as captured:
        response = client.get(url)
    assert response.status_code == status.HTTP_200_OK, response.content
    return sum('FROM "rbac_resourcelastedit"' in query["sql"] for query in captured.captured_queries)


def _make_note(graph, default_org, index):
    return GraphNote.objects.create(graph=graph, content=f"note-{index}")


def _make_llm_config(graph, default_org, index):
    return LLMConfig.objects.create(custom_name=f"config-{index}", org=default_org)


def _make_agent_definition(graph, default_org, index):
    return AgentDefinition.objects.create(name=f"agent-{index}", org=default_org)


def _make_graph(graph, default_org, index):
    return Graph.objects.create(name=f"flow-{index}", org=default_org)


def _make_collection(graph, default_org, index):
    return SourceCollection.objects.create(collection_name=f"docs-{index}", org=default_org)


LIST_CASES = [
    pytest.param("graphnote-list", _make_note, id="graph_note"),
    pytest.param("llmconfig-list", _make_llm_config, id="llm_config"),
    pytest.param("agentdefinition-list", _make_agent_definition, id="agent_definition"),
    pytest.param("graphs-light-list", _make_graph, id="graph_light"),
    pytest.param("sourcecollection-list", _make_collection, id="source_collection"),
]


# Several of these lists already issue other queries per row (content_hash, tags),
# so only the last-edit queries are counted.
@pytest.mark.django_db
@pytest.mark.parametrize(("url_name", "make_row"), LIST_CASES)
def test_list_reads_last_edits_in_one_query(
    url_name, make_row, auth_client, regular_user, graph, default_org
):
    record_last_edit(make_row(graph, default_org, 0), regular_user)
    one_row_count = _count_last_edit_queries(auth_client, reverse(url_name))

    record_last_edits([make_row(graph, default_org, index) for index in (1, 2)], regular_user)
    three_row_count = _count_last_edit_queries(auth_client, reverse(url_name))

    assert one_row_count == three_row_count == 1


# ---- export ----


def _keys_anywhere(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in _keys_anywhere(item)}
    if isinstance(value, list):
        return {key for item in value for key in _keys_anywhere(item)}
    return set()


@pytest.mark.django_db
def test_graph_export_carries_no_last_edit_data(auth_client, regular_user, graph, note):
    record_last_edit(graph, regular_user)

    response = auth_client.get(reverse("graphs-export", args=[graph.pk]))

    assert response.status_code == status.HTTP_200_OK
    exported = json.loads(b"".join(response.streaming_content) if response.streaming else response.content)
    assert not {"last_edited_by", "last_edited_at", "last_edits", "edited_by"} & _keys_anywhere(
        exported
    )


# ---- Graph REST writes compare only the Graph's own fields ----


def _count_patch_queries(client, graph, payload) -> int:
    graph.refresh_from_db()
    with CaptureQueriesContext(connection) as captured:
        response = client.patch(
            reverse("graphs-detail", args=[graph.pk]),
            {**payload, "save_version": graph.save_version},
            format="json",
        )
    assert response.status_code == status.HTTP_200_OK, response.content
    return len(captured.captured_queries)


@pytest.mark.django_db
def test_graph_patch_query_count_does_not_grow_with_nodes(
    auth_client, regular_user, default_org, python_code
):
    small = Graph.objects.create(name="small-patch-flow", org=default_org, created_by=regular_user)
    large = Graph.objects.create(name="large-patch-flow", org=default_org, created_by=regular_user)
    _add_edited_nodes(small, python_code, [regular_user], 1)
    _add_edited_nodes(large, python_code, [regular_user], 3)
    _count_patch_queries(auth_client, small, {"description": "warm-up"})

    small_count = _count_patch_queries(auth_client, small, {"description": "renamed small"})
    large_count = _count_patch_queries(auth_client, large, {"description": "renamed large"})

    assert large_count == small_count


# ---- a failed write leaves no last edit ----


@pytest.mark.django_db
def test_failed_decision_table_write_rolls_back_last_edit(
    colleague_client, regular_user, decision_table
):
    duplicate_groups = _group_payload("a > 1") + _group_payload("a > 2")

    with pytest.raises(IntegrityError):
        colleague_client.patch(
            reverse("decisiontablenode-detail", args=[decision_table.pk]),
            {"node_name": "renamed", "condition_groups": duplicate_groups},
            format="json",
        )

    assert DecisionTableNode.objects.get(pk=decision_table.pk).node_name == "decide"
    last_edit = _last_edit_of(decision_table)
    assert last_edit.edited_by_id == regular_user.id
    assert last_edit.edited_at == PREVIOUS_EDIT_AT


# ---- single-node writes also edit the node's graph ----


@pytest.fixture
def placed_note(graph, regular_user) -> GraphNote:
    note = GraphNote.objects.create(
        graph=graph,
        content="placed",
        metadata={"position": {"x": 1, "y": 1}, "color": "#fff", "size": {"width": 10}},
    )
    record_last_edits([note, graph], regular_user, edited_at=PREVIOUS_EDIT_AT)
    return note


def _upserts(captured) -> int:
    return sum(
        'INSERT INTO "rbac_resourcelastedit"' in query["sql"] for query in captured.captured_queries
    )


def _assert_previous(instance, user) -> None:
    last_edit = _last_edit_of(instance)
    assert last_edit.edited_by_id == user.id, type(instance).__name__
    assert last_edit.edited_at == PREVIOUS_EDIT_AT, type(instance).__name__


@pytest.mark.django_db
def test_single_node_move_edits_graph_not_node(
    colleague_client, colleague, regular_user, graph, placed_note
):
    response = colleague_client.patch(
        reverse("graphnote-detail", args=[placed_note.pk]),
        {"metadata": {"position": {"x": 50, "y": 1}, "color": "#fff", "size": {"width": 10}}},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    _assert_previous(placed_note, regular_user)
    assert _last_edit_of(graph).edited_by_id == colleague.id


@pytest.mark.django_db
def test_single_node_field_change_records_node_and_graph_in_one_statement(
    colleague_client, colleague, graph, placed_note
):
    with CaptureQueriesContext(connection) as captured:
        response = colleague_client.patch(
            reverse("graphnote-detail", args=[placed_note.pk]), {"content": "new"}, format="json"
        )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert _upserts(captured) == 1
    assert _last_edit_of(placed_note).edited_by_id == colleague.id
    assert _last_edit_of(graph).edited_by_id == colleague.id


@pytest.mark.django_db
def test_single_node_appearance_or_no_op_patch_records_nothing(
    colleague_client, regular_user, graph, placed_note
):
    url = reverse("graphnote-detail", args=[placed_note.pk])

    recolored = colleague_client.patch(
        url,
        {"metadata": {"position": {"x": 1, "y": 1}, "color": "#000", "size": {"width": 99}}},
        format="json",
    )
    unchanged = colleague_client.patch(url, {"content": "placed"}, format="json")

    assert recolored.status_code == unchanged.status_code == status.HTTP_200_OK
    _assert_previous(placed_note, regular_user)
    _assert_previous(graph, regular_user)


@pytest.mark.django_db
def test_single_node_create_and_delete_edit_graph(colleague_client, colleague, graph, regular_user):
    record_last_edit(graph, regular_user, edited_at=PREVIOUS_EDIT_AT)

    created = colleague_client.post(
        reverse("graphnote-list"), {"graph": graph.id, "content": "new", "metadata": {}}, format="json"
    )
    assert created.status_code == status.HTTP_201_CREATED, created.content
    assert _last_edit_of(graph).edited_by_id == colleague.id

    record_last_edit(graph, regular_user, edited_at=PREVIOUS_EDIT_AT)
    deleted = colleague_client.delete(reverse("graphnote-detail", args=[created.data["id"]]))

    assert deleted.status_code == status.HTTP_204_NO_CONTENT, deleted.content
    last_edit = _last_edit_of(graph)
    assert last_edit.edited_by_id == colleague.id
    assert last_edit.edited_at > PREVIOUS_EDIT_AT


@pytest.mark.django_db
def test_edge_endpoints_edit_graph_except_waypoints(
    colleague_client, colleague, regular_user, graph, placed_note, python_code
):
    python_node = PythonNode.objects.create(graph=graph, python_code=python_code, node_name="py")
    record_last_edit(graph, regular_user, edited_at=PREVIOUS_EDIT_AT)

    created = colleague_client.post(
        reverse("edge-list"),
        {
            "graph": graph.id,
            "start_node_id": placed_note.id,
            "end_node_id": python_node.id,
            "metadata": {},
        },
        format="json",
    )
    assert created.status_code == status.HTTP_201_CREATED, created.content
    assert _last_edit_of(graph).edited_by_id == colleague.id

    record_last_edit(graph, regular_user, edited_at=PREVIOUS_EDIT_AT)
    rerouted = colleague_client.patch(
        reverse("edge-detail", args=[created.data["id"]]),
        {"metadata": {"waypoints": [{"x": 3, "y": 4}]}},
        format="json",
    )
    assert rerouted.status_code == status.HTTP_200_OK, rerouted.content
    _assert_previous(graph, regular_user)

    deleted = colleague_client.delete(reverse("edge-detail", args=[created.data["id"]]))
    assert deleted.status_code == status.HTTP_204_NO_CONTENT
    assert not Edge.objects.filter(pk=created.data["id"]).exists()
    assert _last_edit_of(graph).edited_by_id == colleague.id


@pytest.mark.django_db
def test_decision_table_view_change_edits_node_and_graph(
    colleague_client, colleague, graph, decision_table
):
    response = colleague_client.patch(
        reverse("decisiontablenode-detail", args=[decision_table.pk]),
        {"condition_groups": _group_payload("a > 5")},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert _last_edit_of(decision_table).edited_by_id == colleague.id
    assert _last_edit_of(graph).edited_by_id == colleague.id
