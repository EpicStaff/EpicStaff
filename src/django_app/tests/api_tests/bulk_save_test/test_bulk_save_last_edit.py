from dataclasses import dataclass
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from rbac.authorship import record_last_edits
from rbac.models import ResourceLastEdit
from tables.models.graph_models import DecisionTableNode, Edge, GraphNote, PythonNode
from tests.fixtures import *  # noqa: F401,F403

PREVIOUS_EDIT_AT = timezone.now() - timedelta(days=2)


def _save_url(graph_id: int) -> str:
    return reverse("graphs-save-flow", args=[graph_id])


# The metadata the flow editor saves for every node (visual-programming/utils/save).
NODE_METADATA = {
    "position": {"x": 100, "y": 200},
    "color": "#5672cd",
    "icon": "code",
    "size": {"width": 330, "height": 60},
    "nodeNumber": 1,
}


def _node_metadata(**changes) -> dict:
    return {**NODE_METADATA, **changes}


def _note_item(graph, **changes) -> dict:
    return {
        "graph": graph.id,
        "content": "note",
        "metadata": {**NODE_METADATA, "backgroundColor": "#ffef9f"},
        **changes,
    }


def _python_item(graph, code="def main(): return 42", **changes) -> dict:
    return {
        "graph": graph.id,
        "node_name": "py",
        "metadata": _node_metadata(),
        "python_code": {"code": code, "entrypoint": "main", "libraries": []},
        **changes,
    }


def _decision_table_item(graph, condition="a > 1", **changes) -> dict:
    return {
        "graph": graph.id,
        "node_name": "decide",
        "metadata": {},
        "condition_groups": [
            {
                "group_name": "g1",
                "group_type": "simple",
                "order": 0,
                "expression": "a > 1",
                "conditions": [{"condition_name": "c1", "condition": condition, "order": 0}],
            }
        ],
        **changes,
    }


def _post_save(client, graph, **lists):
    graph.refresh_from_db()
    response = client.post(
        _save_url(graph.id), {"save_version": graph.save_version, **lists}, format="json"
    )
    assert response.status_code == status.HTTP_200_OK, response.content
    return response


def _last_edit_of(instance) -> ResourceLastEdit | None:
    return ResourceLastEdit.objects.filter(
        content_type=ContentType.objects.get_for_model(instance), object_id=instance.pk
    ).first()


@dataclass
class SavedFlow:
    graph: object
    note: GraphNote
    python_node: PythonNode
    decision_table: DecisionTableNode
    edge: Edge

    def unchanged_payload(self) -> dict:
        return {
            "graph_note_list": [_note_item(self.graph, id=self.note.id)],
            "python_node_list": [_python_item(self.graph, id=self.python_node.id)],
            "decision_table_node_list": [
                _decision_table_item(self.graph, id=self.decision_table.id)
            ],
            "edge_list": [
                {
                    "id": self.edge.id,
                    "graph": self.graph.id,
                    "start_node_id": self.python_node.id,
                    "end_node_id": self.decision_table.id,
                    "metadata": {},
                }
            ],
        }


@pytest.fixture
def previous_editor(db):
    return get_user_model().objects.create_user(
        email="previous-editor@example.com", password="PreviousStrongPass123!"
    )


@pytest.fixture
def created_flow(auth_client, graph) -> SavedFlow:
    _post_save(
        auth_client,
        graph,
        graph_note_list=[_note_item(graph)],
        python_node_list=[_python_item(graph, temp_id="11111111-1111-1111-1111-111111111111")],
        decision_table_node_list=[
            _decision_table_item(graph, temp_id="22222222-2222-2222-2222-222222222222")
        ],
        edge_list=[
            {
                "graph": graph.id,
                "start_temp_id": "11111111-1111-1111-1111-111111111111",
                "end_temp_id": "22222222-2222-2222-2222-222222222222",
                "metadata": {},
            }
        ],
    )
    return SavedFlow(
        graph=graph,
        note=GraphNote.objects.get(graph=graph),
        python_node=PythonNode.objects.get(graph=graph),
        decision_table=DecisionTableNode.objects.get(graph=graph),
        edge=Edge.objects.get(graph=graph),
    )


@pytest.fixture
def saved_flow(created_flow, previous_editor) -> SavedFlow:
    record_last_edits(
        [
            created_flow.graph,
            created_flow.note,
            created_flow.python_node,
            created_flow.decision_table,
        ],
        previous_editor,
        edited_at=PREVIOUS_EDIT_AT,
    )
    return created_flow


def _assert_previous_edit(instance, previous_editor):
    last_edit = _last_edit_of(instance)
    assert last_edit.edited_by_id == previous_editor.id, type(instance).__name__
    assert last_edit.edited_at == PREVIOUS_EDIT_AT, type(instance).__name__


def _assert_edited_now_by(instance, user):
    last_edit = _last_edit_of(instance)
    assert last_edit.edited_by_id == user.id, type(instance).__name__
    assert last_edit.edited_at > PREVIOUS_EDIT_AT, type(instance).__name__


@pytest.mark.django_db
def test_created_nodes_and_graph_are_edited_by_creator(created_flow, regular_user):
    for instance in (
        created_flow.graph,
        created_flow.note,
        created_flow.python_node,
        created_flow.decision_table,
    ):
        _assert_edited_now_by(instance, regular_user)


@pytest.mark.django_db
def test_save_without_changes_records_nothing(auth_client, saved_flow, previous_editor):
    _post_save(auth_client, saved_flow.graph, **saved_flow.unchanged_payload())

    for instance in (
        saved_flow.graph,
        saved_flow.note,
        saved_flow.python_node,
        saved_flow.decision_table,
    ):
        _assert_previous_edit(instance, previous_editor)


@pytest.mark.django_db
def test_edited_node_gets_last_edit_and_unchanged_nodes_keep_theirs(
    auth_client, saved_flow, previous_editor, regular_user
):
    payload = saved_flow.unchanged_payload()
    payload["graph_note_list"] = [_note_item(saved_flow.graph, id=saved_flow.note.id, content="new")]

    _post_save(auth_client, saved_flow.graph, **payload)

    _assert_edited_now_by(saved_flow.note, regular_user)
    _assert_edited_now_by(saved_flow.graph, regular_user)
    _assert_previous_edit(saved_flow.python_node, previous_editor)
    _assert_previous_edit(saved_flow.decision_table, previous_editor)


@pytest.mark.django_db
def test_node_absent_from_payload_keeps_last_edit(
    auth_client, saved_flow, previous_editor, regular_user
):
    _post_save(
        auth_client,
        saved_flow.graph,
        graph_note_list=[_note_item(saved_flow.graph, id=saved_flow.note.id, content="new")],
    )

    _assert_edited_now_by(saved_flow.note, regular_user)
    _assert_previous_edit(saved_flow.python_node, previous_editor)
    _assert_previous_edit(saved_flow.decision_table, previous_editor)


@pytest.mark.django_db
def test_moving_node_edits_graph_but_not_node(
    auth_client, saved_flow, previous_editor, regular_user
):
    moved = _node_metadata(position={"x": 250, "y": 200})
    payload = saved_flow.unchanged_payload()
    payload["python_node_list"] = [
        _python_item(saved_flow.graph, id=saved_flow.python_node.id, metadata=moved)
    ]

    _post_save(auth_client, saved_flow.graph, **payload)

    assert PythonNode.objects.get(pk=saved_flow.python_node.pk).metadata == moved
    _assert_previous_edit(saved_flow.python_node, previous_editor)
    _assert_edited_now_by(saved_flow.graph, regular_user)


@pytest.mark.django_db
def test_moving_and_recoloring_node_edits_graph_only(
    auth_client, saved_flow, previous_editor, regular_user
):
    payload = saved_flow.unchanged_payload()
    payload["python_node_list"] = [
        _python_item(
            saved_flow.graph,
            id=saved_flow.python_node.id,
            metadata=_node_metadata(position={"x": 5, "y": 5}, color="#000000"),
        )
    ]

    _post_save(auth_client, saved_flow.graph, **payload)

    _assert_previous_edit(saved_flow.python_node, previous_editor)
    _assert_edited_now_by(saved_flow.graph, regular_user)


APPEARANCE_CHANGES = [
    pytest.param({"size": {"width": 500, "height": 90}}, id="size"),
    pytest.param({"color": "#000000"}, id="color"),
    pytest.param({"icon": "other"}, id="icon"),
    pytest.param({"nodeNumber": 7}, id="node_number"),
]


@pytest.mark.django_db
@pytest.mark.parametrize("metadata_change", APPEARANCE_CHANGES)
def test_node_appearance_change_records_nothing(
    metadata_change, auth_client, saved_flow, previous_editor
):
    changed = _node_metadata(**metadata_change)
    payload = saved_flow.unchanged_payload()
    payload["python_node_list"] = [
        _python_item(saved_flow.graph, id=saved_flow.python_node.id, metadata=changed)
    ]

    _post_save(auth_client, saved_flow.graph, **payload)

    assert PythonNode.objects.get(pk=saved_flow.python_node.pk).metadata == changed
    _assert_previous_edit(saved_flow.python_node, previous_editor)
    _assert_previous_edit(saved_flow.graph, previous_editor)


@pytest.mark.django_db
def test_note_background_color_change_records_nothing(auth_client, saved_flow, previous_editor):
    payload = saved_flow.unchanged_payload()
    payload["graph_note_list"] = [
        _note_item(
            saved_flow.graph,
            id=saved_flow.note.id,
            metadata={**NODE_METADATA, "backgroundColor": "#000000"},
        )
    ]

    _post_save(auth_client, saved_flow.graph, **payload)

    _assert_previous_edit(saved_flow.note, previous_editor)
    _assert_previous_edit(saved_flow.graph, previous_editor)


@pytest.mark.django_db
def test_python_code_change_is_node_edit(auth_client, saved_flow, previous_editor, regular_user):
    payload = saved_flow.unchanged_payload()
    payload["python_node_list"] = [
        _python_item(
            saved_flow.graph, id=saved_flow.python_node.id, code="def main(): return 7"
        )
    ]

    _post_save(auth_client, saved_flow.graph, **payload)

    _assert_edited_now_by(saved_flow.python_node, regular_user)
    _assert_edited_now_by(saved_flow.graph, regular_user)
    _assert_previous_edit(saved_flow.note, previous_editor)


@pytest.mark.django_db
def test_condition_change_is_decision_table_edit(
    auth_client, saved_flow, previous_editor, regular_user
):
    payload = saved_flow.unchanged_payload()
    payload["decision_table_node_list"] = [
        _decision_table_item(saved_flow.graph, id=saved_flow.decision_table.id, condition="a > 2")
    ]

    _post_save(auth_client, saved_flow.graph, **payload)

    _assert_edited_now_by(saved_flow.decision_table, regular_user)
    _assert_previous_edit(saved_flow.python_node, previous_editor)


@pytest.mark.django_db
def test_deleting_node_edits_graph_only(auth_client, saved_flow, previous_editor, regular_user):
    _post_save(
        auth_client, saved_flow.graph, deleted={"graph_note_ids": [saved_flow.note.id]}
    )

    _assert_edited_now_by(saved_flow.graph, regular_user)
    _assert_previous_edit(saved_flow.python_node, previous_editor)
    assert _last_edit_of(saved_flow.note) is None


@pytest.mark.django_db
def test_new_edge_edits_graph_only(auth_client, saved_flow, previous_editor, regular_user):
    _post_save(
        auth_client,
        saved_flow.graph,
        edge_list=[
            {
                "graph": saved_flow.graph.id,
                "start_node_id": saved_flow.decision_table.id,
                "end_node_id": saved_flow.note.id,
                "metadata": {},
            }
        ],
    )

    _assert_edited_now_by(saved_flow.graph, regular_user)
    _assert_previous_edit(saved_flow.decision_table, previous_editor)
    _assert_previous_edit(saved_flow.note, previous_editor)


@pytest.mark.django_db
def test_save_response_carries_last_edit_fields(
    auth_client, saved_flow, previous_editor, regular_user
):
    payload = saved_flow.unchanged_payload()
    payload["graph_note_list"] = [_note_item(saved_flow.graph, id=saved_flow.note.id, content="new")]

    response = _post_save(auth_client, saved_flow.graph, **payload)

    note = response.data["graph_note_list"][0]
    python_node = response.data["python_node_list"][0]
    assert response.data["last_edited_by"] == regular_user.id
    assert note["last_edited_by"] == regular_user.id
    assert note["last_edited_at"] is not None
    assert python_node["last_edited_by"] == previous_editor.id


@pytest.mark.django_db
def test_edge_waypoints_change_records_nothing(auth_client, saved_flow, previous_editor):
    payload = saved_flow.unchanged_payload()
    payload["edge_list"][0]["metadata"] = {"waypoints": [{"x": 10, "y": 20}]}

    _post_save(auth_client, saved_flow.graph, **payload)

    _assert_previous_edit(saved_flow.graph, previous_editor)
    _assert_previous_edit(saved_flow.python_node, previous_editor)
    _assert_previous_edit(saved_flow.decision_table, previous_editor)


@pytest.mark.django_db
def test_nodes_and_graph_are_recorded_in_one_statement(auth_client, saved_flow, regular_user):
    payload = saved_flow.unchanged_payload()
    payload["graph_note_list"] = [_note_item(saved_flow.graph, id=saved_flow.note.id, content="new")]

    with CaptureQueriesContext(connection) as captured:
        _post_save(auth_client, saved_flow.graph, **payload)

    upserts = [
        query["sql"]
        for query in captured.captured_queries
        if 'INSERT INTO "rbac_resourcelastedit"' in query["sql"]
    ]
    assert len(upserts) == 1
    _assert_edited_now_by(saved_flow.note, regular_user)
    _assert_edited_now_by(saved_flow.graph, regular_user)


@pytest.mark.django_db
def test_failed_save_rolls_back_and_records_nothing(auth_client, saved_flow, previous_editor):
    duplicate_edge = {
        "graph": saved_flow.graph.id,
        "start_node_id": saved_flow.decision_table.id,
        "end_node_id": saved_flow.note.id,
        "metadata": {},
    }
    saved_flow.graph.refresh_from_db()
    payload = {
        "save_version": saved_flow.graph.save_version,
        "graph_note_list": [_note_item(saved_flow.graph, id=saved_flow.note.id, content="lost")],
        # The second identical edge violates the edge unique constraint after the
        # note has already been written inside the same transaction.
        "edge_list": [duplicate_edge, dict(duplicate_edge)],
    }

    with pytest.raises(IntegrityError):
        auth_client.post(_save_url(saved_flow.graph.id), payload, format="json")

    assert GraphNote.objects.get(pk=saved_flow.note.pk).content == "note"
    _assert_previous_edit(saved_flow.note, previous_editor)
    _assert_previous_edit(saved_flow.graph, previous_editor)
