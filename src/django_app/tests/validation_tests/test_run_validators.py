"""The messages a user reads when a flow can't run, from each run-time validator."""

import pytest

from tables.exceptions import (
    EndNodeValidationError,
    FileNodeValidationError,
    SubGraphValidationError,
)
from tables.models import AudioTranscriptionNode, FileExtractorNode, Graph
from tables.models.graph_models import EndNode, SubGraphNode
from tables.validators.end_node_validator import EndNodeValidator
from tables.validators.file_node_validator import FileNodeValidator
from tables.validators.subgraph_validator import SubGraphValidator
from tests.fixtures import *


@pytest.mark.django_db
class TestEndNodeValidator:
    @pytest.mark.parametrize(
        "output_map, expected_message",
        [
            (
                {"summary": "result"},
                'Output "summary" of the End node must be a flow variable, like variables.summary.',
            ),
            (
                {"summary": 42},
                'Output "summary" of the End node must be a flow variable, like variables.summary.',
            ),
            (
                {"summary": "variables.summary", "title": None, "body": "text"},
                'Outputs "body" and "title" of the End node must be flow variables, like '
                "variables.body.",
            ),
            (
                {"summary": "variablesfoo"},
                'Output "summary" of the End node must be a flow variable, like variables.summary.',
            ),
            (
                ["variables.summary"],
                "The End node's Output Map is broken. Set it again.",
            ),
        ],
        ids=[
            "plain-text-value",
            "non-text-value",
            "several-outputs",
            "prefix-without-dot",
            "not-a-map",
        ],
    )
    def test_invalid_output_map_is_refused_with_a_readable_message(
        self, graph, output_map, expected_message
    ):
        EndNode.objects.create(graph=graph, output_map=output_map)

        with pytest.raises(EndNodeValidationError) as error:
            EndNodeValidator().validate(graph_id=graph.id)

        assert str(error.value.detail) == expected_message

    @pytest.mark.parametrize(
        "output_map, expected_message",
        [
            (
                {"summary": "result"},
                'Output "summary" of the End node in flow "Invoice parser" must be a flow '
                "variable, like variables.summary.",
            ),
            (
                ["variables.summary"],
                'The End node in flow "Invoice parser" has a broken Output Map. Set it again.',
            ),
        ],
        ids=["output-not-a-variable", "not-a-map"],
    )
    def test_end_node_inside_a_subflow_names_that_subflow(
        self, graph, output_map, expected_message
    ):
        EndNode.objects.create(graph=graph, output_map=output_map)

        with pytest.raises(EndNodeValidationError) as error:
            EndNodeValidator().validate(graph_id=graph.id, flow_name="Invoice parser")

        assert str(error.value.detail) == expected_message

    @pytest.mark.parametrize(
        "output_map", [{}, {"summary": "variables.summary"}, {"everything": "variables"}]
    )
    def test_outputs_pointing_to_flow_variables_pass(self, graph, output_map):
        end_node = EndNode.objects.create(graph=graph, output_map=output_map)

        assert EndNodeValidator().validate(graph_id=graph.id) == end_node


@pytest.mark.django_db
class TestFileNodeValidator:
    def test_node_without_input_is_named_as_on_the_canvas(self, graph):
        FileExtractorNode.objects.create(
            graph=graph, node_name="Extract PDF", node_number=2, input_map={}
        )

        with pytest.raises(FileNodeValidationError) as error:
            FileNodeValidator().validate_file_nodes(FileExtractorNode.objects.filter(graph=graph))

        assert str(error.value.detail) == 'File Extractor node "Extract PDF #2" has no input file.'

    def test_every_node_without_input_is_listed(self, graph):
        AudioTranscriptionNode.objects.create(
            graph=graph, node_name="Transcribe call", node_number=1, input_map={}
        )
        AudioTranscriptionNode.objects.create(
            graph=graph, node_name="Transcribe memo", node_number=2, input_map={}
        )
        AudioTranscriptionNode.objects.create(
            graph=graph,
            node_name="Transcribe ok",
            node_number=3,
            input_map={"file": "variables.audio"},
        )

        with pytest.raises(FileNodeValidationError) as error:
            FileNodeValidator().validate_file_nodes(
                AudioTranscriptionNode.objects.filter(graph=graph).order_by("node_number")
            )

        assert str(error.value.detail) == (
            'Audio to text nodes "Transcribe call #1" and "Transcribe memo #2" have no input '
            "file."
        )

    def test_both_node_kinds_are_named_in_one_message_grouped_by_kind(self, graph):
        FileExtractorNode.objects.create(
            graph=graph, node_name="Extract PDF", node_number=1, input_map={}
        )
        AudioTranscriptionNode.objects.create(
            graph=graph, node_name="Transcribe call", node_number=2, input_map={}
        )

        with pytest.raises(FileNodeValidationError) as error:
            FileNodeValidator().validate_file_nodes(
                [
                    *FileExtractorNode.objects.filter(graph=graph),
                    *AudioTranscriptionNode.objects.filter(graph=graph),
                ],
                flow_name="Invoice parser",
            )

        assert str(error.value.detail) == (
            'File Extractor node "Extract PDF #1" in flow "Invoice parser" has no input file. '
            'Audio to text node "Transcribe call #2" in flow "Invoice parser" has no input file.'
        )

    def test_nodes_with_input_pass(self, graph):
        FileExtractorNode.objects.create(
            graph=graph, node_name="Extract PDF", input_map={"file": "variables.pdf"}
        )

        FileNodeValidator().validate_file_nodes(FileExtractorNode.objects.filter(graph=graph))


@pytest.fixture
def child_flow(default_org) -> Graph:
    return Graph.objects.create(name="Invoice parser", org=default_org)


@pytest.mark.django_db
class TestSubGraphValidator:
    def test_node_running_its_own_flow_is_named_not_the_flow(self, graph):
        SubGraphNode.objects.create(
            graph=graph, node_name="Run again", node_number=4, subgraph=graph
        )

        with pytest.raises(SubGraphValidationError) as error:
            SubGraphValidator().validate(graph)

        assert str(error.value.detail) == (
            'Subflow node "Run again #4" runs its own flow. Choose another flow.'
        )

    def test_loop_through_another_flow_names_the_node_on_this_canvas_and_its_flow(
        self, graph, child_flow
    ):
        SubGraphNode.objects.create(
            graph=graph, node_name="Parse invoice", node_number=2, subgraph=child_flow
        )
        SubGraphNode.objects.create(
            graph=child_flow, node_name="Back to parent", node_number=1, subgraph=graph
        )

        with pytest.raises(SubGraphValidationError) as error:
            SubGraphValidator().validate(graph)

        assert str(error.value.detail) == (
            'Subflow node "Parse invoice #2" makes a loop through flow "Invoice parser". '
            "Choose another flow."
        )

    @pytest.mark.parametrize(
        "loop_closes_at, expected_message",
        [
            (
                "flow_b",
                'Subflow node "Parse invoice #2" leads to a loop in flow "Step C". '
                "Choose another flow there.",
            ),
            (
                "root",
                'Subflow node "Parse invoice #2" makes a loop through flow "Step B". '
                "Choose another flow.",
            ),
        ],
        ids=["A-B-C-B", "A-B-C-A"],
    )
    def test_loop_deeper_in_the_chain_is_found_and_names_where_it_closes(
        self, graph, default_org, loop_closes_at, expected_message
    ):
        flow_b = Graph.objects.create(name="Step B", org=default_org)
        flow_c = Graph.objects.create(name="Step C", org=default_org)
        SubGraphNode.objects.create(
            graph=graph, node_name="Parse invoice", node_number=2, subgraph=flow_b
        )
        SubGraphNode.objects.create(graph=flow_b, node_name="To C", subgraph=flow_c)
        SubGraphNode.objects.create(
            graph=flow_c,
            node_name="Back",
            subgraph={"flow_b": flow_b, "root": graph}[loop_closes_at],
        )

        with pytest.raises(SubGraphValidationError) as error:
            SubGraphValidator().validate(graph)

        assert str(error.value.detail) == expected_message

    def test_flow_running_itself_deeper_in_the_chain_is_found(self, graph, child_flow):
        SubGraphNode.objects.create(
            graph=graph, node_name="Parse invoice", node_number=2, subgraph=child_flow
        )
        SubGraphNode.objects.create(graph=child_flow, node_name="Again", subgraph=child_flow)

        with pytest.raises(SubGraphValidationError) as error:
            SubGraphValidator().validate(graph)

        assert str(error.value.detail) == (
            'Subflow node "Parse invoice #2" leads to a loop in flow "Invoice parser". '
            "Choose another flow there."
        )

    def test_node_without_a_flow_is_refused(self, graph):
        SubGraphNode.objects.create(graph=graph, node_name="Parse invoice", node_number=2)

        with pytest.raises(SubGraphValidationError) as error:
            SubGraphValidator().validate(graph)

        assert str(error.value.detail) == 'Subflow node "Parse invoice #2" has no flow selected.'

    def test_node_without_a_flow_inside_a_subflow_names_that_subflow(self, graph, child_flow):
        SubGraphNode.objects.create(
            graph=graph, node_name="Parse invoice", node_number=2, subgraph=child_flow
        )
        SubGraphNode.objects.create(graph=child_flow, node_name="Nested", node_number=1)

        with pytest.raises(SubGraphValidationError) as error:
            SubGraphValidator().validate(graph)

        assert str(error.value.detail) == (
            'Subflow node "Nested #1" in flow "Invoice parser" has no flow selected.'
        )

    def test_subflows_without_a_loop_pass(self, graph, child_flow):
        SubGraphNode.objects.create(graph=graph, node_name="Parse invoice", subgraph=child_flow)
        SubGraphNode.objects.create(graph=graph, node_name="Parse again", subgraph=child_flow)

        SubGraphValidator().validate(graph)
