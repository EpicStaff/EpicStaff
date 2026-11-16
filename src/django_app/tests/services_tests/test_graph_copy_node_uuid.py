"""A copied flow gets new node uuids; the source keeps its own."""

import pytest

from tables.services.copy_services import GraphCopyService
from tests.fixtures import *  # noqa: F401,F403
from tests.graph_node_builders import NODE_MODELS, create_node, node_uuids_by_model


@pytest.mark.django_db
@pytest.mark.parametrize("model", NODE_MODELS, ids=lambda model: model.__name__)
def test_graph_copy_gives_new_node_uuid(graph, model):
    node = create_node(model, graph)

    copied_graph = GraphCopyService().copy(graph)

    [copied_uuid] = node_uuids_by_model(copied_graph, [model])[model]
    assert copied_uuid != node.uuid
    assert node_uuids_by_model(graph, [model])[model] == [node.uuid]
