"""Node uuid through bulk save: create input, update immutability, uniqueness inside the graph."""

from unittest import mock
from uuid import UUID, uuid4

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from tables.models import Graph
from tables.models.base_models import NodeIdentityMixin
from tables.models.graph_models import (
    AgentNode,
    AudioTranscriptionNode,
    ClassificationDecisionTableNode,
    DecisionTableNode,
    EndNode,
    FileExtractorNode,
    GraphNote,
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
from tables.services.graph_bulk_save_service.node_uuid_validator import (
    DUPLICATE_UUID_MESSAGE,
    TAKEN_UUID_MESSAGE,
    NodeUuidValidator,
)
from tables.services.graph_bulk_save_service.registry import NODE_TYPE_REGISTRY
from tests.fixtures import *  # noqa: F401,F403
from tests.graph_node_builders import NODE_MODELS, create_node
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

_PYTHON_CODE_DATA = {"code": "def main(): return 42", "entrypoint": "main", "libraries": []}

# The smallest valid bulk-save item of each node type, apart from `graph`.
_NODE_PAYLOADS = {
    PythonNode: {"python_code": _PYTHON_CODE_DATA},
    FileExtractorNode: {"node_name": "file extractor"},
    KeyValueNode: {"node_name": "key value"},
    AudioTranscriptionNode: {"node_name": "audio transcription"},
    StartNode: {"variables": {}},
    EndNode: {"output_map": {"context": "variables"}},
    SubGraphNode: {"node_name": "subgraph"},
    ClassificationDecisionTableNode: {"node_name": "classification decision table"},
    DecisionTableNode: {"node_name": "decision table"},
    GraphNote: {"content": "note", "metadata": {}},
    KnowledgeNode: {"node_name": "knowledge"},
    WebhookTriggerNode: {
        "node_name": "webhook trigger",
        "python_code": _PYTHON_CODE_DATA,
        "metadata": {},
    },
    TelegramTriggerNode: {"node_name": "telegram trigger", "fields": []},
    ScheduleTriggerNode: {"node_name": "schedule trigger"},
    TaskNode: {"node_name": "task"},
    AgentNode: {"node_name": "agent"},
}

_NODE_CONFIGS = pytest.mark.parametrize(
    "config", NODE_TYPE_REGISTRY, ids=[config.list_key for config in NODE_TYPE_REGISTRY]
)


def _save_url(graph_id: int) -> str:
    return reverse("graphs-save-flow", args=[graph_id])


def _node_payload(model, graph: Graph, **overrides) -> dict:
    return {"graph": graph.id, **_NODE_PAYLOADS[model], **overrides}


def _save(client, graph: Graph, **lists):
    payload = {"save_version": graph.save_version, **lists}
    return client.post(_save_url(graph.id), payload, format="json")


def _uuid_error(response, list_key: str, index: int = 0) -> list:
    item_errors = [item for item in response.data["errors"][list_key] if item["index"] == index]
    return item_errors[0]["errors"]["uuid"]


def _all_active_node_count(graph: Graph) -> int:
    return sum(config.model_class.objects.filter(graph=graph).count() for config in NODE_TYPE_REGISTRY)


def test_registry_covers_every_node_model_with_a_uuid():
    # The validator maps deleted ids to models through the registry.
    assert {config.model_class for config in NODE_TYPE_REGISTRY} == set(
        NodeIdentityMixin.get_node_models()
    )


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@_NODE_CONFIGS
def test_create_stores_and_returns_client_uuid(auth_client, graph, config):
    client_uuid = uuid4()

    response = _save(
        auth_client,
        graph,
        **{config.list_key: [_node_payload(config.model_class, graph, uuid=str(client_uuid))]},
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    node = config.model_class.objects.get(graph=graph)
    assert node.uuid == client_uuid
    assert [item["uuid"] for item in response.data[config.list_key]] == [str(client_uuid)]


@pytest.mark.django_db
def test_create_without_uuid_generates_one(auth_client, graph):
    response = _save(auth_client, graph, graph_note_list=[_node_payload(GraphNote, graph)])

    assert response.status_code == status.HTTP_200_OK, response.content
    node = GraphNote.objects.get(graph=graph)
    assert isinstance(node.uuid, UUID)
    assert response.data["graph_note_list"][0]["uuid"] == str(node.uuid)


@pytest.mark.django_db
def test_create_accepts_a_uuid_without_dashes(auth_client, graph):
    client_uuid = uuid4()

    response = _save(
        auth_client,
        graph,
        graph_note_list=[_node_payload(GraphNote, graph, uuid=client_uuid.hex)],
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert GraphNote.objects.get(graph=graph).uuid == client_uuid


@pytest.mark.django_db
@pytest.mark.parametrize(
    "malformed_uuid, message",
    [
        ("not-a-uuid", "Must be a valid UUID."),
        ("1234", "Must be a valid UUID."),
        (42, "Must be a valid UUID."),
        (True, "Must be a valid UUID."),
        ([str(uuid4())], "Must be a valid UUID."),
        ({"uuid": str(uuid4())}, "Must be a valid UUID."),
        (None, "This field may not be null."),
    ],
    ids=["text", "short-digits", "integer", "boolean", "list", "dict", "null"],
)
def test_create_with_malformed_uuid_returns_400(auth_client, graph, malformed_uuid, message):
    response = _save(
        auth_client,
        graph,
        graph_note_list=[
            _node_payload(GraphNote, graph, uuid=str(uuid4())),
            _node_payload(GraphNote, graph, uuid=malformed_uuid),
        ],
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    # The exact body proves the malformed value is not echoed back.
    assert response.data["errors"] == {
        "graph_note_list": [{"index": 1, "errors": {"uuid": [message]}}]
    }
    assert not GraphNote.objects.filter(graph=graph).exists()


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@_NODE_CONFIGS
def test_update_accepts_unchanged_uuid(auth_client, graph, config):
    node = create_node(config.model_class, graph)

    response = _save(
        auth_client,
        graph,
        **{
            config.list_key: [
                _node_payload(config.model_class, graph, id=node.id, uuid=str(node.uuid))
            ]
        },
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    stored_uuid = node.uuid
    node.refresh_from_db()
    assert node.uuid == stored_uuid
    assert response.data[config.list_key][0]["uuid"] == str(stored_uuid)


@pytest.mark.django_db
@_NODE_CONFIGS
def test_update_with_changed_uuid_returns_400(auth_client, graph, config):
    node = create_node(config.model_class, graph)
    stored_uuid = node.uuid
    save_version = graph.save_version

    response = _save(
        auth_client,
        graph,
        **{
            config.list_key: [
                _node_payload(config.model_class, graph, id=node.id, uuid=str(uuid4()))
            ]
        },
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert _uuid_error(response, config.list_key) == ["A node uuid cannot be changed."]
    node.refresh_from_db()
    assert node.uuid == stored_uuid
    graph.refresh_from_db()
    assert graph.save_version == save_version


@pytest.mark.django_db
def test_update_without_uuid_keeps_stored_uuid(auth_client, graph):
    note = create_node(GraphNote, graph)
    stored_uuid = note.uuid

    response = _save(
        auth_client,
        graph,
        graph_note_list=[_node_payload(GraphNote, graph, id=note.id, content="edited")],
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    note.refresh_from_db()
    assert note.content == "edited"
    assert note.uuid == stored_uuid


@pytest.mark.django_db
def test_update_echoing_another_nodes_uuid_returns_400(auth_client, graph):
    note = create_node(GraphNote, graph)
    other_note = create_node(GraphNote, graph)

    response = _save(
        auth_client,
        graph,
        graph_note_list=[_node_payload(GraphNote, graph, id=note.id, uuid=str(other_note.uuid))],
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert _uuid_error(response, "graph_note_list") == ["A node uuid cannot be changed."]


# ---------------------------------------------------------------------------
# Uniqueness inside the graph
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_duplicate_uuid_in_one_list_returns_400(auth_client, graph):
    shared_uuid = str(uuid4())

    response = _save(
        auth_client,
        graph,
        graph_note_list=[
            _node_payload(GraphNote, graph, uuid=shared_uuid),
            _node_payload(GraphNote, graph, uuid=shared_uuid),
        ],
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert _uuid_error(response, "graph_note_list", index=0) == [DUPLICATE_UUID_MESSAGE]
    assert _uuid_error(response, "graph_note_list", index=1) == [DUPLICATE_UUID_MESSAGE]
    assert shared_uuid not in response.content.decode()
    assert _all_active_node_count(graph) == 0


@pytest.mark.django_db
def test_duplicate_uuid_across_node_types_returns_400(auth_client, graph):
    shared_uuid = str(uuid4())

    response = _save(
        auth_client,
        graph,
        graph_note_list=[_node_payload(GraphNote, graph, uuid=shared_uuid)],
        python_node_list=[_node_payload(PythonNode, graph, uuid=shared_uuid)],
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert _uuid_error(response, "graph_note_list") == [DUPLICATE_UUID_MESSAGE]
    assert _uuid_error(response, "python_node_list") == [DUPLICATE_UUID_MESSAGE]
    assert _all_active_node_count(graph) == 0


@pytest.mark.django_db
@pytest.mark.parametrize("existing_model", NODE_MODELS, ids=lambda model: model.__name__)
def test_uuid_of_an_existing_node_in_any_table_returns_400(auth_client, graph, existing_model):
    existing_node = create_node(existing_model, graph)
    save_version = graph.save_version

    response = _save(
        auth_client,
        graph,
        python_node_list=[_node_payload(PythonNode, graph, uuid=str(existing_node.uuid))],
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.data["errors"] == {
        "python_node_list": [{"index": 0, "errors": {"uuid": [TAKEN_UUID_MESSAGE]}}]
    }
    assert _all_active_node_count(graph) == 1
    graph.refresh_from_db()
    assert graph.save_version == save_version


@pytest.mark.django_db
def test_uuid_of_a_soft_deleted_node_is_accepted(auth_client, graph):
    soft_deleted_note = create_node(GraphNote, graph)
    GraphNote.all_objects.filter(id=soft_deleted_note.id).update(
        is_soft_deleted=True, soft_deleted_at=timezone.now()
    )

    response = _save(
        auth_client,
        graph,
        python_node_list=[_node_payload(PythonNode, graph, uuid=str(soft_deleted_note.uuid))],
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert PythonNode.objects.get(graph=graph).uuid == soft_deleted_note.uuid


@pytest.mark.django_db
def test_uuid_of_a_node_deleted_in_the_same_request_is_accepted(auth_client, graph):
    deleted_note = create_node(GraphNote, graph)

    response = _save(
        auth_client,
        graph,
        python_node_list=[_node_payload(PythonNode, graph, uuid=str(deleted_note.uuid))],
        deleted={"graph_note_ids": [deleted_note.id]},
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert not GraphNote.objects.filter(id=deleted_note.id).exists()
    assert PythonNode.objects.get(graph=graph).uuid == deleted_note.uuid


@pytest.mark.django_db
def test_uuid_of_a_node_in_another_graph_of_the_same_org_is_accepted(
    auth_client, graph, default_org
):
    other_graph = Graph.objects.create(name="other", org=default_org)
    other_note = create_node(GraphNote, other_graph)

    response = _save(
        auth_client,
        graph,
        graph_note_list=[_node_payload(GraphNote, graph, uuid=str(other_note.uuid))],
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert GraphNote.objects.get(graph=graph).uuid == other_note.uuid
    other_note.refresh_from_db()
    assert other_note.graph_id == other_graph.id


@pytest.mark.django_db
def test_uuid_of_a_node_in_another_org_is_accepted_and_leaks_nothing(
    client_as, admin_acme, acme, beta
):
    acme_graph = Graph.objects.create(name="acme flow", org=acme)
    beta_graph = Graph.objects.create(name="beta flow", org=beta)
    beta_note = create_node(GraphNote, beta_graph, content="beta secret note")
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    response = _save(
        client,
        acme_graph,
        graph_note_list=[_node_payload(GraphNote, acme_graph, uuid=str(beta_note.uuid))],
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert "beta secret note" not in response.content.decode()
    acme_note = GraphNote.objects.get(graph=acme_graph)
    assert acme_note.uuid == beta_note.uuid
    assert acme_note.content == "note"
    beta_note.refresh_from_db()
    assert beta_note.graph_id == beta_graph.id
    assert beta_note.content == "beta secret note"


@pytest.mark.django_db
def test_bulk_save_into_another_orgs_graph_with_a_uuid_returns_404(
    client_as, admin_acme, acme, beta
):
    beta_graph = Graph.objects.create(name="beta flow", org=beta)
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    response = _save(
        client,
        beta_graph,
        graph_note_list=[_node_payload(GraphNote, beta_graph, uuid=str(uuid4()))],
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content
    assert not GraphNote.objects.filter(graph=beta_graph).exists()


@pytest.mark.django_db
def test_conflict_found_only_at_write_time_returns_400(auth_client, graph):
    """Safety net: a uuid constraint violation at write time is a 400, never a 500.

    No current writer reaches it (save_version serialises them), so the check is
    bypassed to force the violation. A note is used because StartNode and EndNode
    violate their one-per-graph index first.
    """
    existing_note = create_node(GraphNote, graph)
    save_version = graph.save_version

    # Bypass the Pass 1 check so the insert hits the database constraint.
    with mock.patch.object(NodeUuidValidator, "find_errors", return_value={}):
        response = _save(
            auth_client,
            graph,
            graph_note_list=[
                _node_payload(GraphNote, graph, content="new"),
                _node_payload(GraphNote, graph, uuid=str(existing_note.uuid)),
            ],
        )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.data["errors"] == {"nodes": [TAKEN_UUID_MESSAGE]}
    assert list(GraphNote.objects.filter(graph=graph)) == [existing_note]
    graph.refresh_from_db()
    assert graph.save_version == save_version


@pytest.mark.django_db
def test_create_with_uuids_keeps_temp_id_edge_mapping(auth_client, graph):
    start_uuid, python_uuid = uuid4(), uuid4()
    start_temp_id, python_temp_id = str(uuid4()), str(uuid4())

    response = _save(
        auth_client,
        graph,
        start_node_list=[
            _node_payload(StartNode, graph, uuid=str(start_uuid), temp_id=start_temp_id)
        ],
        python_node_list=[
            _node_payload(PythonNode, graph, uuid=str(python_uuid), temp_id=python_temp_id)
        ],
        edge_list=[
            {"graph": graph.id, "start_temp_id": start_temp_id, "end_temp_id": python_temp_id}
        ],
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    start_node = StartNode.objects.get(graph=graph)
    python_node = PythonNode.objects.get(graph=graph)
    assert (start_node.uuid, python_node.uuid) == (start_uuid, python_uuid)
    edge = graph.edge_list.get()
    assert (edge.start_node_id, edge.end_node_id) == (start_node.id, python_node.id)
