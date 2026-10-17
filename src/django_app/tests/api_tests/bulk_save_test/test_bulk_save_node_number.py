import pytest
from django.urls import reverse
from rest_framework import status

from tables.models import Graph
from tables.models.graph_models import PythonNode
from tables.models.python_models import PythonCode
from tests.fixtures import *  # noqa: F401,F403

_PYTHON_CODE_DATA = {"code": "def main(): return 42", "entrypoint": "main", "libraries": []}

# One create payload (besides `graph`, `node_name` and the hint) per numbered node list, in
# NODE_TYPE_REGISTRY order — the order bulk save writes them in.
NUMBERED_CREATE_PAYLOADS = {
    "python_node_list": {"python_code": _PYTHON_CODE_DATA},
    "file_extractor_node_list": {},
    "key_value_node_list": {},
    "audio_transcription_node_list": {},
    "subgraph_node_list": {},
    "classification_decision_table_node_list": {},
    "decision_table_node_list": {},
    "knowledge_node_list": {},
    "webhook_trigger_node_list": {"python_code": _PYTHON_CODE_DATA, "metadata": {}},
    "telegram_trigger_node_list": {"fields": []},
    "schedule_trigger_node_list": {},
    "task_node_list": {},
    "agent_node_list": {},
}


def _save(client, graph: Graph, **node_lists):
    graph.refresh_from_db()
    return client.post(
        reverse("graphs-save-flow", args=[graph.id]),
        {"save_version": graph.save_version, **node_lists},
        format="json",
    )


def _new(list_key: str, graph: Graph, node_name: str, hint: int | None = None) -> dict:
    item = {"graph": graph.id, "node_name": node_name, **NUMBERED_CREATE_PAYLOADS[list_key]}
    if hint is not None:
        item["node_number_hint"] = hint
    return item


def _python(graph: Graph, node_name: str, hint: int | None = None) -> dict:
    return _new("python_node_list", graph, node_name, hint)


def _numbers_by_name(response) -> dict[str, int]:
    assert response.status_code == status.HTTP_200_OK, response.content
    return {
        node["node_name"]: node["node_number"]
        for list_key in NUMBERED_CREATE_PAYLOADS
        for node in response.data[list_key]
    }


def _graph_seq(graph: Graph) -> int:
    graph.refresh_from_db()
    return graph.node_number_seq


def _python_node(graph: Graph, node_name: str) -> PythonNode:
    python_code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    return PythonNode.objects.create(graph=graph, python_code=python_code, node_name=node_name)


@pytest.fixture
def graph_with_python_nodes_1_and_2_then_2_deleted(graph) -> Graph:
    _python_node(graph, "kept")
    _python_node(graph, "deleted").delete()
    return graph


@pytest.mark.django_db
def test_hints_keep_creation_order_across_types(auth_client, graph):
    # Canvas order: python #1, agent #2, python #3 — the registry writes both pythons first.
    response = _save(
        auth_client,
        graph,
        python_node_list=[_python(graph, "first", hint=1), _python(graph, "third", hint=3)],
        agent_node_list=[_new("agent_node_list", graph, "second", hint=2)],
    )

    assert _numbers_by_name(response) == {"first": 1, "second": 2, "third": 3}
    assert _graph_seq(graph) == 3


@pytest.mark.django_db
def test_hint_is_not_echoed_in_the_response(auth_client, graph):
    response = _save(auth_client, graph, python_node_list=[_python(graph, "only", hint=1)])

    assert response.status_code == status.HTTP_200_OK, response.content
    [node] = response.data["python_node_list"]
    assert "node_number_hint" not in node


@pytest.mark.django_db
def test_hint_outside_block_is_replaced(auth_client, graph):
    response = _save(
        auth_client, graph, python_node_list=[_python(graph, "only", hint=2_147_483_647)]
    )

    assert _numbers_by_name(response) == {"only": 1}
    assert _graph_seq(graph) == 1


@pytest.mark.django_db
def test_hint_of_a_deleted_node_is_not_reused(
    auth_client, graph_with_python_nodes_1_and_2_then_2_deleted
):
    graph = graph_with_python_nodes_1_and_2_then_2_deleted

    response = _save(auth_client, graph, python_node_list=[_python(graph, "new", hint=2)])

    assert _numbers_by_name(response)["new"] == 3
    assert _graph_seq(graph) == 3


@pytest.mark.django_db
def test_duplicate_hints_get_distinct_numbers(auth_client, graph):
    response = _save(
        auth_client,
        graph,
        python_node_list=[_python(graph, "a", hint=1), _python(graph, "b", hint=1)],
    )

    assert _numbers_by_name(response) == {"a": 1, "b": 2}


@pytest.mark.django_db
def test_unhinted_node_takes_the_number_left_by_hinted_ones(auth_client, graph):
    response = _save(
        auth_client,
        graph,
        python_node_list=[_python(graph, "unhinted"), _python(graph, "hinted", hint=1)],
    )

    assert _numbers_by_name(response) == {"unhinted": 2, "hinted": 1}


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("python_hint", "agent_hint", "expected"),
    [
        # The registry writes python before agent; the leftovers follow the hints instead.
        pytest.param(9, 4, {"python": 2, "agent": 1}, id="hints-above-block-keep-their-order"),
        pytest.param(None, 7, {"python": 2, "agent": 1}, id="unhinted-goes-after-hinted"),
        pytest.param(5, 5, {"python": 1, "agent": 2}, id="equal-hints-keep-registry-order"),
    ],
)
def test_leftover_numbers_follow_hint_order_in_a_new_graph(
    auth_client, graph, python_hint, agent_hint, expected
):
    response = _save(
        auth_client,
        graph,
        python_node_list=[_python(graph, "python", hint=python_hint)],
        agent_node_list=[_new("agent_node_list", graph, "agent", hint=agent_hint)],
    )

    assert _numbers_by_name(response) == expected


@pytest.mark.django_db
def test_update_ignores_hint_and_keeps_number(auth_client, graph):
    existing = _python_node(graph, "existing")

    response = _save(
        auth_client,
        graph,
        python_node_list=[{**_python(graph, "existing", hint=50), "id": existing.id}],
    )

    assert _numbers_by_name(response) == {"existing": 1}
    assert _graph_seq(graph) == 1


@pytest.mark.django_db
def test_updated_node_does_not_consume_a_block_number(auth_client, graph):
    existing = _python_node(graph, "existing")

    response = _save(
        auth_client,
        graph,
        python_node_list=[
            {**_python(graph, "existing"), "id": existing.id},
            _python(graph, "new", hint=2),
        ],
    )

    assert _numbers_by_name(response) == {"existing": 1, "new": 2}
    assert _graph_seq(graph) == 2


@pytest.mark.django_db
def test_unnumbered_nodes_do_not_consume_block_numbers(auth_client, graph):
    response = _save(
        auth_client,
        graph,
        start_node_list=[{"graph": graph.id, "variables": {}}],
        end_node_list=[{"graph": graph.id, "output_map": {}}],
        graph_note_list=[{"graph": graph.id, "content": "note", "metadata": {}}],
        python_node_list=[_python(graph, "only", hint=1)],
    )

    assert _numbers_by_name(response) == {"only": 1}
    assert _graph_seq(graph) == 1


@pytest.mark.django_db
@pytest.mark.parametrize("hint", [0, -1])
def test_hint_below_one_is_rejected(auth_client, graph, hint):
    response = _save(auth_client, graph, python_node_list=[_python(graph, "only", hint=hint)])

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert not PythonNode.objects.filter(graph=graph).exists()
    assert _graph_seq(graph) == 0


@pytest.mark.django_db
def test_two_classification_decision_tables_with_the_same_name_save(auth_client, graph):
    list_key = "classification_decision_table_node_list"

    response = _save(
        auth_client,
        graph,
        **{list_key: [_new(list_key, graph, "Router"), _new(list_key, graph, "Router")]},
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert sorted(node["node_number"] for node in response.data[list_key]) == [1, 2]


@pytest.mark.django_db
@pytest.mark.parametrize("list_key", list(NUMBERED_CREATE_PAYLOADS))
def test_every_numbered_node_type_receives_its_hint(auth_client, graph, list_key):
    # Hints run against registry order, so a type only gets its hint when its
    # saveable passes the assigned number through to the model.
    node_count = len(NUMBERED_CREATE_PAYLOADS)
    node_lists = {
        key: [_new(key, graph, key, hint=node_count - position)]
        for position, key in enumerate(NUMBERED_CREATE_PAYLOADS)
    }

    response = _save(auth_client, graph, **node_lists)

    expected_number = node_count - list(NUMBERED_CREATE_PAYLOADS).index(list_key)
    assert _numbers_by_name(response)[list_key] == expected_number
    assert _graph_seq(graph) == node_count
