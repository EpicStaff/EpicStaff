import pytest
from django.urls import reverse
from rest_framework import status

from tables.models.graph_models import (
    AgentNode,
    AudioTranscriptionNode,
    ClassificationDecisionTableNode,
    DecisionTableNode,
    EndNode,
    FileExtractorNode,
    KeyValueNode,
    KnowledgeNode,
    PythonNode,
    ScheduleTriggerNode,
    StartNode,
    SubGraphNode,
    TaskNode,
    TelegramTriggerNode,
    WebhookTriggerNode,
)
from tables.models.python_models import PythonCode
from tests.fixtures import *  # noqa: F401,F403

_PYTHON_CODE_DATA = {"code": "def main(): return 42", "entrypoint": "main", "libraries": []}


def _python_code() -> PythonCode:
    return PythonCode.objects.create(code="def main(): return 1", entrypoint="main")


# list key in the graph payload -> factory creating one node of that type in a graph
NUMBERED_NODE_FACTORIES = {
    "python_node_list": lambda graph: PythonNode.objects.create(
        graph=graph, python_code=_python_code()
    ),
    "file_extractor_node_list": lambda graph: FileExtractorNode.objects.create(graph=graph),
    "key_value_node_list": lambda graph: KeyValueNode.objects.create(graph=graph),
    "audio_transcription_node_list": lambda graph: AudioTranscriptionNode.objects.create(
        graph=graph
    ),
    "webhook_trigger_node_list": lambda graph: WebhookTriggerNode.objects.create(
        graph=graph, node_name="webhook", python_code=_python_code()
    ),
    "decision_table_node_list": lambda graph: DecisionTableNode.objects.create(
        graph=graph, node_name="decision"
    ),
    "classification_decision_table_node_list": (
        lambda graph: ClassificationDecisionTableNode.objects.create(
            graph=graph, node_name="classification"
        )
    ),
    "subgraph_node_list": lambda graph: SubGraphNode.objects.create(graph=graph),
    "knowledge_node_list": lambda graph: KnowledgeNode.objects.create(graph=graph),
    "task_node_list": lambda graph: TaskNode.objects.create(graph=graph),
    "agent_node_list": lambda graph: AgentNode.objects.create(graph=graph),
    "telegram_trigger_node_list": lambda graph: TelegramTriggerNode.objects.create(
        graph=graph, node_name="telegram"
    ),
    "schedule_trigger_node_list": lambda graph: ScheduleTriggerNode.objects.create(
        graph=graph, node_name="schedule"
    ),
}

# Single-node create payloads (besides `graph`) for the bulk-save endpoint, for the types whose
# serializers spell out their fields (or are not ModelSerializers) plus two `__all__` types.
BULK_CREATE_PAYLOADS = {
    "python_node_list": {"python_code": _PYTHON_CODE_DATA},
    "decision_table_node_list": {"node_name": "decision"},
    "classification_decision_table_node_list": {"node_name": "classification"},
    "webhook_trigger_node_list": {
        "node_name": "webhook",
        "python_code": _PYTHON_CODE_DATA,
        "metadata": {},
    },
    "telegram_trigger_node_list": {"node_name": "telegram", "fields": []},
    "schedule_trigger_node_list": {"node_name": "schedule"},
}

# Detail routes of the numbered node types whose serializers are not `__all__`.
DETAIL_ROUTES = {
    "python_node_list": "pythonnode-detail",
    "decision_table_node_list": "decisiontablenode-detail",
    "classification_decision_table_node_list": "classificationdecisiontablenode-detail",
    "webhook_trigger_node_list": "webhooktriggernode-detail",
    "telegram_trigger_node_list": "telegramtriggernode-detail",
    "schedule_trigger_node_list": "scheduletriggernode-detail",
}


def _save_url(graph_id: int) -> str:
    return reverse("graphs-save-flow", args=[graph_id])


def _graph_url(graph_id: int) -> str:
    return reverse("graphs-detail", args=[graph_id])


@pytest.fixture
def graph_with_every_numbered_node(graph):
    for factory in NUMBERED_NODE_FACTORIES.values():
        factory(graph)
    StartNode.objects.create(graph=graph, variables={})
    EndNode.objects.create(graph=graph, output_map={})
    return graph


@pytest.mark.django_db
@pytest.mark.parametrize("list_key", list(NUMBERED_NODE_FACTORIES))
def test_graph_detail_exposes_node_number_on_every_numbered_node(
    auth_client, graph_with_every_numbered_node, list_key
):
    response = auth_client.get(_graph_url(graph_with_every_numbered_node.id))

    assert response.status_code == status.HTTP_200_OK, response.content
    [node] = response.data[list_key]
    assert isinstance(node["node_number"], int)


@pytest.mark.django_db
def test_graph_detail_numbers_are_distinct_per_graph(auth_client, graph_with_every_numbered_node):
    response = auth_client.get(_graph_url(graph_with_every_numbered_node.id))

    numbers = sorted(
        response.data[list_key][0]["node_number"] for list_key in NUMBERED_NODE_FACTORIES
    )
    assert numbers == list(range(1, len(NUMBERED_NODE_FACTORIES) + 1))
    assert response.data["node_number_seq"] == len(NUMBERED_NODE_FACTORIES)


@pytest.mark.django_db
@pytest.mark.parametrize("list_key", ["start_node_list", "end_node_list"])
def test_structural_nodes_expose_no_node_number(
    auth_client, graph_with_every_numbered_node, list_key
):
    response = auth_client.get(_graph_url(graph_with_every_numbered_node.id))

    [node] = response.data[list_key]
    assert "node_number" not in node


@pytest.mark.django_db
def test_patch_python_node_cannot_change_node_number(auth_client, graph):
    node = NUMBERED_NODE_FACTORIES["python_node_list"](graph)
    assert node.node_number == 1

    response = auth_client.patch(
        reverse("pythonnode-detail", args=[node.id]),
        {"node_number": 99, "node_name": "renamed"},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    node.refresh_from_db()
    assert node.node_name == "renamed"
    assert node.node_number == 1
    assert response.data["node_number"] == 1


@pytest.mark.django_db
@pytest.mark.parametrize("list_key", list(DETAIL_ROUTES))
def test_patch_cannot_change_node_number_on_any_serializer_style(auth_client, graph, list_key):
    node = NUMBERED_NODE_FACTORIES[list_key](graph)

    response = auth_client.patch(
        reverse(DETAIL_ROUTES[list_key], args=[node.id]),
        {"node_number": 99},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    node.refresh_from_db()
    assert node.node_number == 1
    assert response.data["node_number"] == 1


@pytest.mark.django_db
def test_patch_graph_cannot_change_node_number_seq(auth_client, graph):
    NUMBERED_NODE_FACTORIES["python_node_list"](graph)
    graph.refresh_from_db()
    assert graph.node_number_seq == 1

    response = auth_client.patch(_graph_url(graph.id), {"node_number_seq": 0, "save_version": graph.save_version}, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    graph.refresh_from_db()
    assert graph.node_number_seq == 1
    assert response.data["node_number_seq"] == 1


@pytest.mark.django_db
@pytest.mark.parametrize("list_key", list(BULK_CREATE_PAYLOADS))
def test_bulk_save_ignores_node_number_on_create(auth_client, graph, list_key):
    node_payload = {"graph": graph.id, "node_number": 99, **BULK_CREATE_PAYLOADS[list_key]}

    response = auth_client.post(
        _save_url(graph.id),
        {"save_version": graph.save_version, list_key: [node_payload]},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    [node] = response.data[list_key]
    assert node["node_number"] == 1
    assert response.data["node_number_seq"] == 1


@pytest.mark.django_db
@pytest.mark.parametrize("list_key", list(BULK_CREATE_PAYLOADS))
def test_bulk_save_ignores_node_number_on_update(auth_client, graph, list_key):
    node = NUMBERED_NODE_FACTORIES[list_key](graph)
    assert node.node_number == 1
    node_payload = {
        "id": node.id,
        "graph": graph.id,
        "node_number": 99,
        **BULK_CREATE_PAYLOADS[list_key],
        "node_name": "renamed",
    }

    response = auth_client.post(
        _save_url(graph.id),
        {"save_version": graph.save_version, list_key: [node_payload]},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    [saved] = response.data[list_key]
    assert saved["id"] == node.id
    assert saved["node_number"] == 1
    assert response.data["node_number_seq"] == 1
