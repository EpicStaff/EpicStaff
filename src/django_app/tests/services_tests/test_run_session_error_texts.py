"""The texts a user reads when Run refuses a flow before it starts.

Each case builds a broken flow, runs it through `POST /run-session/` and pins the exact
sentence the flows list and the editor show.
"""

import pytest
from django.urls import reverse
from rest_framework import status

from tables.models import (
    AudioTranscriptionNode,
    Edge,
    EndNode,
    FileExtractorNode,
    Graph,
    KnowledgeNode,
    PythonCode,
    PythonNode,
    StartNode,
    SubGraphNode,
)
from tests.fixtures import redis_client_mock  # noqa: F401
from tests.error_envelope import details_by_attr


def _flow(org, name: str) -> tuple[Graph, StartNode]:
    graph = Graph.objects.create(name=name, org=org)
    return graph, StartNode.objects.create(graph=graph, variables={})


def _connect(graph: Graph, start_node: StartNode, node) -> None:
    Edge.objects.create(graph=graph, start_node_id=start_node.pk, end_node_id=node.pk)


def _connect_leaf(graph: Graph, start_node: StartNode) -> None:
    leaf = PythonNode.objects.create(
        graph=graph,
        node_name="leaf",
        python_code=PythonCode.objects.create(code="def main(): return 1"),
    )
    _connect(graph, start_node, leaf)


def _subflow(graph: Graph, start_node: StartNode, subgraph: Graph | None, name: str, number: int):
    node = SubGraphNode.objects.create(
        graph=graph, subgraph=subgraph, node_name=name, node_number=number
    )
    _connect(graph, start_node, node)
    return node


def _main_with_child(org) -> tuple[Graph, Graph, StartNode]:
    """Main runs Child through a Subflow node; the broken part goes into Child."""
    main, main_start = _flow(org, "Main")
    child, child_start = _flow(org, "Child")
    _subflow(main, main_start, child, "Run child", 1)
    return main, child, child_start


def _subflow_start_not_connected(org) -> Graph:
    main, _child, _child_start = _main_with_child(org)
    return main


def _end_output_map(output_map, *, in_child: bool):
    def build(org) -> Graph:
        if in_child:
            main, graph, start_node = _main_with_child(org)
        else:
            main, start_node = _flow(org, "Main")
            graph = main
        _connect_leaf(graph, start_node)
        EndNode.objects.create(graph=graph, output_map=output_map)
        return main

    return build


def _file_node(model, name: str, number: int, *, in_child: bool):
    def build(org) -> Graph:
        if in_child:
            main, graph, start_node = _main_with_child(org)
        else:
            main, start_node = _flow(org, "Main")
            graph = main
        node = model.objects.create(
            graph=graph, node_name=name, node_number=number, input_map={}
        )
        _connect(graph, start_node, node)
        return main

    return build


def _knowledge_node(*, in_child: bool):
    def build(org) -> Graph:
        if in_child:
            main, graph, start_node = _main_with_child(org)
        else:
            main, start_node = _flow(org, "Main")
            graph = main
        node = KnowledgeNode.objects.create(graph=graph, node_name="Search", node_number=4)
        _connect(graph, start_node, node)
        return main

    return build


def _subflow_runs_own_flow(org) -> Graph:
    main, main_start = _flow(org, "Main")
    _subflow(main, main_start, main, "Again", 1)
    return main


def _subflow_in_child_runs_own_flow(org) -> Graph:
    main, child, child_start = _main_with_child(org)
    _subflow(child, child_start, child, "Again", 2)
    return main


def _subflow_loop_through_run_flow(org) -> Graph:
    main, child, child_start = _main_with_child(org)
    _subflow(child, child_start, main, "Back to main", 2)
    return main


def _subflow_loop_deeper(org) -> Graph:
    main, child, child_start = _main_with_child(org)
    grandchild, grandchild_start = _flow(org, "Grandchild")
    _subflow(child, child_start, grandchild, "Run grandchild", 2)
    _subflow(grandchild, grandchild_start, child, "Back to child", 3)
    return main


def _subflow_without_flow(org) -> Graph:
    main, main_start = _flow(org, "Main")
    _subflow(main, main_start, None, "Empty", 5)
    return main


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("build_flow", "expected_text"),
    [
        pytest.param(
            _subflow_start_not_connected,
            'No node connected to start node in flow "Child".',
            id="subflow-start-not-connected",
        ),
        pytest.param(
            _end_output_map(["variables.result"], in_child=False),
            "The End node's Output Map is broken.",
            id="end-output-map-not-a-map",
        ),
        pytest.param(
            _end_output_map({"result": 5}, in_child=False),
            "The End node's Output Map is broken.",
            id="end-output-value-not-text",
        ),
        pytest.param(
            _end_output_map({"result": "state.result"}, in_child=False),
            'Output "result" of the End node isn\'t a flow variable.',
            id="end-output-not-a-variable",
        ),
        pytest.param(
            _file_node(FileExtractorNode, "Read", 2, in_child=False),
            'File Extractor node "Read #2" has no input file.',
            id="file-extractor-no-input",
        ),
        pytest.param(
            _file_node(AudioTranscriptionNode, "Listen", 3, in_child=False),
            'Audio to text node "Listen #3" has no input file.',
            id="audio-no-input",
        ),
        pytest.param(
            _knowledge_node(in_child=False),
            'Knowledge Retriever node "Search #4" has no collection, RAG or query.',
            id="knowledge-not-set-up",
        ),
        pytest.param(
            _end_output_map(["variables.result"], in_child=True),
            'The End node\'s Output Map is broken in flow "Child".',
            id="subflow-end-output-map-not-a-map",
        ),
        pytest.param(
            _end_output_map({"result": "state.result"}, in_child=True),
            'Output "result" of the End node isn\'t a flow variable in flow "Child".',
            id="subflow-end-output-not-a-variable",
        ),
        pytest.param(
            _file_node(FileExtractorNode, "Read", 2, in_child=True),
            'File Extractor node "Read #2" has no input file in flow "Child".',
            id="subflow-file-extractor-no-input",
        ),
        pytest.param(
            _file_node(AudioTranscriptionNode, "Listen", 3, in_child=True),
            'Audio to text node "Listen #3" has no input file in flow "Child".',
            id="subflow-audio-no-input",
        ),
        pytest.param(
            _knowledge_node(in_child=True),
            'Knowledge Retriever node "Search #4" has no collection, RAG or query '
            'in flow "Child".',
            id="subflow-knowledge-not-set-up",
        ),
        pytest.param(
            _subflow_runs_own_flow,
            'Subflow node "Again #1" runs its own flow.',
            id="subflow-runs-own-flow",
        ),
        pytest.param(
            _subflow_in_child_runs_own_flow,
            'Subflow node "Again #2" runs its own flow in flow "Child".',
            id="subflow-in-subflow-runs-own-flow",
        ),
        pytest.param(
            _subflow_loop_through_run_flow,
            'Subflow node "Run child #1" makes a loop through flow "Child".',
            id="subflow-loop-through-run-flow",
        ),
        pytest.param(
            _subflow_loop_deeper,
            'Subflow node "Run child #1" leads to a loop in flow "Child".',
            id="subflow-loop-deeper",
        ),
        pytest.param(
            _subflow_without_flow,
            'Subflow node "Empty #5" has no flow selected.',
            id="subflow-without-flow",
        ),
    ],
)
def test_run_refused_with_the_fact(
    auth_client, redis_client_mock, default_org, build_flow, expected_text  # noqa: F811
):
    main = build_flow(default_org)

    response = auth_client.post(
        reverse("run-session"), {"graph_id": main.pk, "variables": {}}, format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert details_by_attr(response.json()) == {None: [expected_text]}
