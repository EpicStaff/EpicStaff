import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from rbac.models import OrganizationUser
from tables.models.graph_models import (
    ClassificationDecisionTableNode,
    DecisionTableNode,
    GraphNote,
    PythonNode,
    ScheduleTriggerNode,
    StartNode,
    TelegramTriggerNode,
)
from tests.fixtures import *  # noqa: F401,F403
from tests.user_summary_helpers import expected_user_summary

_PYTHON_CODE_DATA = {"code": "def main(): return 42", "entrypoint": "main", "libraries": []}


@pytest.fixture
def editor(db, default_org, org_admin_role):
    user = get_user_model().objects.create_user(
        email="node-editor@example.com", password="EditorStrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=default_org, role=org_admin_role)
    return user


@pytest.fixture
def editor_client(editor, default_org) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=editor)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(default_org.id))
    return client


def _list_url(basename: str) -> str:
    return reverse(f"{basename}-list")


def _detail_url(basename: str, pk: int) -> str:
    return reverse(f"{basename}-detail", args=[pk])


def _author_id(model, pk: int) -> int | None:
    return model._base_manager.values_list("created_by_id", flat=True).get(pk=pk)


# ---- REST create ----


@pytest.mark.django_db
def test_create_graph_note_stamps_acting_user(auth_client, regular_user, graph):
    response = auth_client.post(
        _list_url("graphnote"),
        {"graph": graph.id, "content": "hello", "metadata": {}},
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert _author_id(GraphNote, response.data["id"]) == regular_user.id
    assert response.data["created_by"] == expected_user_summary(regular_user)


@pytest.mark.django_db
def test_create_start_node_stamps_acting_user_and_shows_author(auth_client, regular_user, graph):
    response = auth_client.post(
        _list_url("startnode"), {"graph": graph.id, "variables": {}}, format="json"
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert _author_id(StartNode, response.data["id"]) == regular_user.id
    assert response.data["created_by"] == expected_user_summary(regular_user)


@pytest.mark.django_db
def test_create_schedule_trigger_node_stamps_acting_user(auth_client, regular_user, graph):
    response = auth_client.post(
        _list_url("scheduletriggernode"),
        {"graph": graph.id, "node_name": "nightly"},
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert _author_id(ScheduleTriggerNode, response.data["id"]) == regular_user.id
    assert response.data["created_by"] == expected_user_summary(regular_user)


@pytest.mark.django_db
def test_create_python_node_stamps_acting_user(auth_client, regular_user, graph):
    response = auth_client.post(
        _list_url("pythonnode"),
        {"graph": graph.id, "node_name": "py", "python_code": _PYTHON_CODE_DATA},
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert _author_id(PythonNode, response.data["id"]) == regular_user.id


@pytest.mark.django_db
def test_create_telegram_trigger_node_stamps_acting_user(
    auth_client, regular_user, graph, mock_telegram_service
):
    response = auth_client.post(
        _list_url("telegramtriggernode"),
        {"graph": graph.id, "node_name": "telegram", "fields": []},
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert _author_id(TelegramTriggerNode, response.data["id"]) == regular_user.id
    assert response.data["created_by"] == expected_user_summary(regular_user)


@pytest.mark.django_db
def test_create_decision_table_node_stamps_acting_user(auth_client, regular_user, graph):
    response = auth_client.post(
        _list_url("decisiontablenode"),
        {"graph": graph.id, "node_name": "decide", "condition_groups": []},
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert _author_id(DecisionTableNode, response.data["id"]) == regular_user.id


@pytest.mark.django_db
def test_create_classification_decision_table_node_stamps_acting_user(
    auth_client, regular_user, graph
):
    response = auth_client.post(
        _list_url("classificationdecisiontablenode"),
        {"graph": graph.id, "node_name": "classify"},
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert _author_id(ClassificationDecisionTableNode, response.data["id"]) == regular_user.id
    assert response.data["created_by"] == expected_user_summary(regular_user)


def _spoofed_author(user, shape: str):
    if shape == "id":
        return user.id
    return {"id": user.id, "display_name": "Spoofed", "avatar_url": None}


@pytest.mark.django_db
@pytest.mark.parametrize("shape", ["id", "summary"])
def test_created_by_in_create_body_is_ignored(shape, auth_client, regular_user, editor, graph):
    response = auth_client.post(
        _list_url("graphnote"),
        {
            "graph": graph.id,
            "content": "spoof",
            "metadata": {},
            "created_by": _spoofed_author(editor, shape),
        },
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert _author_id(GraphNote, response.data["id"]) == regular_user.id
    assert response.data["created_by"] == expected_user_summary(regular_user)


# ---- REST update ----


def _python_node(graph, python_code):
    return PythonNode.objects.create(graph=graph, python_code=python_code, node_name="py")


UPDATE_CASES = [
    pytest.param(
        lambda graph, python_code: GraphNote.objects.create(graph=graph, content="note"),
        "graphnote",
        {"content": "edited"},
        id="graph_note",
    ),
    pytest.param(
        lambda graph, python_code: StartNode.objects.create(graph=graph, variables={}),
        "startnode",
        {"variables": {"topic": "x"}},
        id="start_node",
    ),
    pytest.param(_python_node, "pythonnode", {"node_name": "renamed"}, id="python_node"),
    pytest.param(
        lambda graph, python_code: ScheduleTriggerNode.objects.create(
            graph=graph, node_name="nightly"
        ),
        "scheduletriggernode",
        {"node_name": "renamed"},
        id="schedule_trigger_node",
    ),
    pytest.param(
        lambda graph, python_code: TelegramTriggerNode.objects.create(
            graph=graph, node_name="telegram"
        ),
        "telegramtriggernode",
        {"node_name": "renamed"},
        id="telegram_trigger_node",
    ),
    pytest.param(
        lambda graph, python_code: DecisionTableNode.objects.create(
            graph=graph, node_name="decide"
        ),
        "decisiontablenode",
        {"node_name": "renamed"},
        id="decision_table_node",
    ),
    pytest.param(
        lambda graph, python_code: ClassificationDecisionTableNode.objects.create(
            graph=graph, node_name="classify"
        ),
        "classificationdecisiontablenode",
        {"pre_input_map": {"a": "b"}},
        id="classification_decision_table_node",
    ),
]


@pytest.mark.django_db
@pytest.mark.parametrize(("make_node", "basename", "payload"), UPDATE_CASES)
def test_update_of_unauthored_node_claims_editor(
    make_node, basename, payload, editor_client, editor, graph, python_code, mock_telegram_service
):
    node = make_node(graph, python_code)

    response = editor_client.patch(_detail_url(basename, node.pk), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert _author_id(type(node), node.pk) == editor.id


@pytest.mark.django_db
@pytest.mark.parametrize(("make_node", "basename", "payload"), UPDATE_CASES)
def test_update_of_authored_node_keeps_author(
    make_node,
    basename,
    payload,
    editor_client,
    regular_user,
    graph,
    python_code,
    mock_telegram_service,
):
    node = make_node(graph, python_code)
    type(node)._base_manager.filter(pk=node.pk).update(created_by=regular_user)

    response = editor_client.patch(_detail_url(basename, node.pk), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert _author_id(type(node), node.pk) == regular_user.id


@pytest.mark.django_db
@pytest.mark.parametrize("shape", ["id", "summary"])
def test_created_by_in_update_body_is_ignored(shape, editor_client, editor, regular_user, graph):
    note = GraphNote.objects.create(graph=graph, content="note")

    response = editor_client.patch(
        _detail_url("graphnote", note.pk),
        {"content": "edited", "created_by": _spoofed_author(regular_user, shape)},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert _author_id(GraphNote, note.pk) == editor.id
    assert response.data["created_by"] == expected_user_summary(editor)


@pytest.mark.django_db
def test_created_by_in_update_body_cannot_replace_author(
    editor_client, editor, regular_user, graph
):
    note = GraphNote.objects.create(graph=graph, content="note", created_by=regular_user)

    response = editor_client.patch(
        _detail_url("graphnote", note.pk),
        {"content": "edited", "created_by": editor.id},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert _author_id(GraphNote, note.pk) == regular_user.id


# ---- idempotent create ----


@pytest.mark.django_db
def test_idempotent_create_on_unauthored_node_claims_editor(
    editor_client, editor, graph, python_code
):
    node = _python_node(graph, python_code)

    response = editor_client.post(
        _list_url("pythonnode"),
        {"graph": graph.id, "node_name": node.node_name, "python_code": _PYTHON_CODE_DATA},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["id"] == node.pk
    assert _author_id(PythonNode, node.pk) == editor.id


@pytest.mark.django_db
def test_idempotent_create_on_authored_node_keeps_author(
    editor_client, regular_user, graph, python_code
):
    node = _python_node(graph, python_code)
    PythonNode.objects.filter(pk=node.pk).update(created_by=regular_user)

    response = editor_client.post(
        _list_url("pythonnode"),
        {"graph": graph.id, "node_name": node.node_name, "python_code": _PYTHON_CODE_DATA},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert _author_id(PythonNode, node.pk) == regular_user.id


@pytest.mark.django_db
def test_idempotent_decision_table_create_on_unauthored_node_claims_editor(
    editor_client, editor, graph
):
    node = DecisionTableNode.objects.create(graph=graph, node_name="decide")

    response = editor_client.post(
        _list_url("decisiontablenode"),
        {"graph": graph.id, "node_name": "decide", "condition_groups": []},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert _author_id(DecisionTableNode, node.pk) == editor.id


# ---- graph bulk save ----


def _save_url(graph_id: int) -> str:
    return reverse("graphs-save-flow", args=[graph_id])


@pytest.mark.django_db
def test_bulk_save_create_stamps_acting_user(auth_client, regular_user, graph):
    payload = {
        "save_version": graph.save_version,
        "graph_note_list": [{"graph": graph.id, "content": "bulk", "metadata": {}}],
        "start_node_list": [{"graph": graph.id, "variables": {}}],
        "python_node_list": [{"graph": graph.id, "python_code": _PYTHON_CODE_DATA}],
        "schedule_trigger_node_list": [{"graph": graph.id, "node_name": "nightly"}],
    }

    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    for model in (GraphNote, StartNode, PythonNode, ScheduleTriggerNode):
        authors = set(model.objects.filter(graph=graph).values_list("created_by_id", flat=True))
        assert authors == {regular_user.id}, model.__name__


@pytest.mark.django_db
def test_bulk_save_update_claims_unauthored_and_keeps_authored(
    editor_client, editor, regular_user, graph, python_code
):
    unauthored_note = GraphNote.objects.create(graph=graph, content="free")
    authored_note = GraphNote.objects.create(
        graph=graph, content="owned", created_by=regular_user
    )
    unauthored_python = _python_node(graph, python_code)
    payload = {
        "save_version": graph.save_version,
        "graph_note_list": [
            {"id": unauthored_note.id, "graph": graph.id, "content": "a", "metadata": {}},
            {
                "id": authored_note.id,
                "graph": graph.id,
                "content": "b",
                "metadata": {},
                "created_by": editor.id,
            },
        ],
        "python_node_list": [
            {
                "id": unauthored_python.id,
                "graph": graph.id,
                "node_name": "renamed",
                "python_code": _PYTHON_CODE_DATA,
            }
        ],
    }

    response = editor_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert _author_id(GraphNote, unauthored_note.pk) == editor.id
    assert _author_id(GraphNote, authored_note.pk) == regular_user.id
    assert _author_id(PythonNode, unauthored_python.pk) == editor.id
    assert GraphNote.objects.get(pk=authored_note.pk).content == "b"
