"""Bulk save writes only into the flow in the URL, whatever flow an item names."""

import pytest
from django.urls import reverse
from rest_framework import status

from tables.models import Graph
from tables.models.graph_models import GraphNote, PythonNode
from tests.fixtures import *  # noqa: F401,F403
from tests.graph_node_builders import create_node

_PYTHON_CODE_DATA = {"code": "def main(): return 42", "entrypoint": "main", "libraries": []}


@pytest.mark.django_db
def test_create_naming_another_flow_lands_in_the_url_flow(auth_client, graph, default_org):
    other_graph = Graph.objects.create(name="other flow", org=default_org)
    other_note = create_node(GraphNote, other_graph)

    response = auth_client.post(
        reverse("graphs-save-flow", args=[graph.id]),
        {
            "save_version": graph.save_version,
            "python_node_list": [
                {
                    "graph": other_graph.id,
                    "python_code": _PYTHON_CODE_DATA,
                    "uuid": str(other_note.uuid),
                }
            ],
        },
        format="json",
    )

    # The uuid is unique per flow, so a uuid taken only in the other flow is free here.
    assert response.status_code == status.HTTP_200_OK, response.content
    assert PythonNode.objects.get(graph=graph).uuid == other_note.uuid
    assert not PythonNode.objects.filter(graph=other_graph).exists()
