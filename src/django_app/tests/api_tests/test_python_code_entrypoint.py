"""`entrypoint` of a PythonCode written through each node endpoint, the bulk save and the
python code tool endpoint.

Invariant: only a plain Python name that is not a keyword is stored. Anything else is a
400 and changes nothing, instead of being accepted and refused later by the sandbox.
"""

import pytest
from django.db.models import Model
from django.urls import reverse
from rest_framework import status

from tables.models import Graph, PythonCode, PythonCodeTool
from tests.python_code_slots import PYTHON_CODE_SLOT_IDS, PYTHON_CODE_SLOTS, PythonCodeSlot

CODE = "def main(**kwargs): return 1"

INVALID_ENTRYPOINTS = [
    '(lambda f, *_: f)(main, "filler", __import__("os").system("id"))',
    "obj.method",
    "main()",
    "1main",
    "class",
    "None",
]
INVALID_ENTRYPOINT_IDS = ["expression", "dotted", "call", "leading-digit", "keyword", "None"]


@pytest.fixture(params=PYTHON_CODE_SLOTS, ids=PYTHON_CODE_SLOT_IDS)
def slot(request) -> PythonCodeSlot:
    return request.param


@pytest.fixture
def node(slot, graph):
    return slot.create(graph, PythonCode.objects.create(code=CODE, entrypoint="main"))


def _python_code(entrypoint: str) -> dict:
    return {"code": CODE, "entrypoint": entrypoint}


def _stored_entrypoint(slot: PythonCodeSlot, node_id: int) -> str:
    node = slot.model.objects.select_related(slot.code_field).get(pk=node_id)
    return slot.python_code_of(node).entrypoint


def _bulk_save(client, slot: PythonCodeSlot, graph: Graph, entry: dict):
    graph.refresh_from_db()
    return client.post(
        reverse("graphs-save-flow", args=[graph.id]),
        {"save_version": graph.save_version, slot.graph_list_key: [entry]},
        format="json",
    )


@pytest.mark.django_db
class TestNodeEndpoint:
    def test_create_stores_a_function_name(self, auth_client, graph, slot):
        response = auth_client.post(
            reverse(f"{slot.basename}-list"),
            slot.request_body(graph, _python_code("handle_event")),
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content
        assert _stored_entrypoint(slot, response.data["id"]) == "handle_event"

    @pytest.mark.parametrize("entrypoint", INVALID_ENTRYPOINTS, ids=INVALID_ENTRYPOINT_IDS)
    def test_create_rejects_anything_but_a_function_name(self, auth_client, graph, slot, entrypoint):
        python_code_count_before = PythonCode.objects.count()

        response = auth_client.post(
            reverse(f"{slot.basename}-list"),
            slot.request_body(graph, _python_code(entrypoint)),
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert "entrypoint" in response.content.decode()
        assert not slot.model.objects.filter(graph=graph).exists()
        assert PythonCode.objects.count() == python_code_count_before

    @pytest.mark.parametrize("entrypoint", INVALID_ENTRYPOINTS, ids=INVALID_ENTRYPOINT_IDS)
    def test_update_rejects_anything_but_a_function_name(self, auth_client, slot, node, entrypoint):
        response = auth_client.patch(
            reverse(f"{slot.basename}-detail", args=[node.id]),
            {slot.code_field: _python_code(entrypoint)},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert "entrypoint" in response.content.decode()
        assert _stored_entrypoint(slot, node.id) == "main"


@pytest.mark.django_db
@pytest.mark.parametrize("entrypoint", INVALID_ENTRYPOINTS, ids=INVALID_ENTRYPOINT_IDS)
def test_bulk_save_rejects_anything_but_a_function_name(auth_client, graph, slot, node, entrypoint):
    entry = slot.request_body(graph, _python_code(entrypoint), id=node.id)

    response = _bulk_save(auth_client, slot, graph, entry)

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert "entrypoint" in response.content.decode()
    assert _stored_entrypoint(slot, node.id) == "main"


@pytest.mark.django_db
@pytest.mark.parametrize("entrypoint", INVALID_ENTRYPOINTS, ids=INVALID_ENTRYPOINT_IDS)
def test_python_code_tool_rejects_anything_but_a_function_name(auth_client, entrypoint):
    response = auth_client.post(
        reverse("pythoncodetool-list"),
        {"name": "entrypoint-tool", "description": "tool", "python_code": _python_code(entrypoint)},
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert "entrypoint" in response.content.decode()
    assert not PythonCodeTool.objects.filter(name="entrypoint-tool").exists()
