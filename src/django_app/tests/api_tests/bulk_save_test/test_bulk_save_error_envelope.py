"""A refused flow save names each problem by node list, position and field, and writes nothing."""

import pytest
from django.urls import reverse
from rest_framework import status

from tables.models import Graph
from tables.models.graph_models import ClassificationDecisionTableNode, PythonNode
from tests.error_envelope import details_by_attr
from tests.fixtures import *  # noqa: F401,F403

REFUSED_UNDERSCORE_KEY = (
    "Placeholder '{a._b}' is not allowed: '_b' starts with '_'. Rename that variable or key."
)


def _save(client, graph: Graph, **payload):
    graph.refresh_from_db()
    return client.post(
        reverse("graphs-save-flow", args=[graph.id]),
        {"save_version": graph.save_version, **payload},
        format="json",
    )


@pytest.mark.django_db
def test_a_nested_field_of_a_node_is_named_by_list_position_and_path(auth_client, graph):
    response = _save(
        auth_client,
        graph,
        classification_decision_table_node_list=[
            {"node_name": "Fine"},
            {
                "node_name": "Classifier",
                "prompt_configs": [
                    {"prompt_key": "fine", "prompt_text": "Rate {topic}"},
                    {"prompt_key": "bad", "prompt_text": "Rate {a._b}"},
                ],
            },
        ],
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.data["type"] == "client_error"
    assert details_by_attr(response.data) == {
        "classification_decision_table_node_list.1.prompt_configs.1.prompt_text": [
            REFUSED_UNDERSCORE_KEY
        ]
    }
    assert not ClassificationDecisionTableNode.objects.filter(graph=graph).exists()


@pytest.mark.django_db
def test_a_serializer_error_keeps_its_field_code(auth_client, graph):
    response = _save(
        auth_client,
        graph,
        python_node_list=[{"node_name": "Code", "python_code": {"entrypoint": "main"}}],
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert [(item["attr"], item["code"]) for item in response.data["errors"]] == [
        ("python_node_list.0.python_code.code", "required")
    ]
    assert not PythonNode.objects.filter(graph=graph).exists()


@pytest.mark.django_db
def test_problems_of_a_whole_item_or_list_name_the_item_or_the_list(auth_client, graph):
    response = _save(
        auth_client,
        graph,
        python_node_list=[
            {
                "id": 987654,
                "node_name": "Gone",
                "python_code": {"code": "def main(): pass", "entrypoint": "main"},
            }
        ],
        deleted={"python_node_ids": [987655]},
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert details_by_attr(response.data) == {
        "deleted": [f"python_node_ids: IDs [987655] not found in graph {graph.id}"],
        "python_node_list.0": [f"id=987654 not found in graph {graph.id}"],
    }


@pytest.mark.django_db
def test_a_malformed_payload_is_named_by_its_field(auth_client, graph):
    response = auth_client.post(
        reverse("graphs-save-flow", args=[graph.id]), {"python_node_list": []}, format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert [(item["attr"], item["code"]) for item in response.data["errors"]] == [
        ("save_version", "required")
    ]
