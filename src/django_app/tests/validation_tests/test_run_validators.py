"""The messages a user reads when a flow can't run, from each run-time validator."""

import pytest

from agents.models import AgentDefinition
from django.utils import timezone

from tables.exceptions import (
    AgentNodeRunValidationError,
    ClassificationDecisionTableNodeRunValidationError,
    DecisionTableNodeRunValidationError,
    EndNodeValidationError,
    FileNodeValidationError,
    KeyValueNodeRunValidationError,
    SubGraphNodeRunValidationError,
    SubGraphValidationError,
)
from tables.models import (
    AudioTranscriptionNode,
    FileExtractorNode,
    Graph,
    KeyValueNode,
    KeyValueTable,
    LLMConfig,
)
from tables.models.graph_models import (
    AgentNode,
    AgentNodeTask,
    ClassificationConditionGroup,
    ClassificationDecisionTableNode,
    ClassificationDecisionTablePrompt,
    Condition,
    ConditionGroup,
    DecisionTableNode,
    EndNode,
    SubGraphNode,
    TaskNode,
)
from tables.validators.agent_node_validator import AgentNodeValidator
from tables.validators.decision_table_node_validator import (
    ClassificationDecisionTableNodeValidator,
    DecisionTableNodeValidator,
)
from tables.validators.end_node_validator import EndNodeValidator
from tables.validators.file_node_validator import FileNodeValidator
from tables.validators.key_value_node_validator import KeyValueNodeValidator
from tables.validators.subgraph_node_validator import SubGraphNodeValidator
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


def _agent(org, name: str, llm_config=None) -> AgentDefinition:
    return AgentDefinition.objects.create(org=org, name=name, llm_config=llm_config)


def _agent_node(graph, node_name: str, node_number: int, agent=None, task_count: int = 1):
    agent_node = AgentNode.objects.create(
        graph=graph, node_name=node_name, node_number=node_number, agent_definition=agent
    )
    for order in range(task_count):
        AgentNodeTask.objects.create(agent_node=agent_node, name=f"Task {order}", order=order)
    return agent_node


def _task_node(graph, node_name: str, node_number: int, agent=None) -> TaskNode:
    return TaskNode.objects.create(
        graph=graph, node_name=node_name, node_number=node_number, agent_definition=agent
    )


def _validate_agent_nodes(graph, flow_name: str | None = None) -> None:
    agent_nodes = (
        AgentNode.objects.filter(graph=graph)
        .select_related("agent_definition")
        .prefetch_related("tasks")
        .order_by("node_number", "id")
    )
    task_nodes = (
        TaskNode.objects.filter(graph=graph)
        .select_related("agent_definition")
        .order_by("node_number", "id")
    )
    AgentNodeValidator().validate_runnable([*agent_nodes, *task_nodes], flow_name=flow_name)


@pytest.mark.django_db
class TestAgentNodeValidatorNoAgent:
    def test_agent_node_without_an_agent_is_named(self, graph):
        _agent_node(graph, "Writer", 2)

        with pytest.raises(AgentNodeRunValidationError) as error:
            _validate_agent_nodes(graph)

        assert str(error.value.detail) == 'Agent node "Writer #2" has no agent chosen.'

    def test_task_node_without_an_agent_is_named(self, graph):
        _task_node(graph, "Summarize", 4)

        with pytest.raises(AgentNodeRunValidationError) as error:
            _validate_agent_nodes(graph)

        assert str(error.value.detail) == 'Task node "Summarize #4" has no agent chosen.'

    def test_several_task_nodes_without_an_agent_are_listed(self, graph):
        _task_node(graph, "A", 1)
        _task_node(graph, "B", 2)

        with pytest.raises(AgentNodeRunValidationError) as error:
            _validate_agent_nodes(graph)

        assert str(error.value.detail) == 'Task nodes "A #1" and "B #2" have no agent chosen.'

    def test_both_node_kinds_get_a_sentence_each_agent_nodes_first(self, graph):
        _task_node(graph, "Summarize", 1)
        _agent_node(graph, "Writer", 2)
        _agent_node(graph, "Editor", 3)

        with pytest.raises(AgentNodeRunValidationError) as error:
            _validate_agent_nodes(graph)

        assert str(error.value.detail) == (
            'Agent nodes "Writer #2" and "Editor #3" have no agent chosen. '
            'Task node "Summarize #1" has no agent chosen.'
        )

    def test_nodes_inside_a_subflow_name_that_subflow(self, graph):
        _agent_node(graph, "Writer", 2)
        _task_node(graph, "A", 3)
        _task_node(graph, "B", 4)

        with pytest.raises(AgentNodeRunValidationError) as error:
            _validate_agent_nodes(graph, flow_name="Invoice parser")

        assert str(error.value.detail) == (
            'Agent node "Writer #2" in flow "Invoice parser" has no agent chosen. '
            'Task nodes "A #3" and "B #4" in flow "Invoice parser" have no agent chosen.'
        )

    def test_missing_agent_is_reported_before_a_missing_llm_or_tasks(self, graph, default_org):
        _agent_node(graph, "Writer", 1, agent=_agent(default_org, "Copywriter"))
        _agent_node(graph, "Planner", 2, agent=_agent(default_org, "Lead"), task_count=0)
        _task_node(graph, "Summarize", 3)

        with pytest.raises(AgentNodeRunValidationError) as error:
            _validate_agent_nodes(graph)

        assert str(error.value.detail) == 'Task node "Summarize #3" has no agent chosen.'


@pytest.mark.django_db
class TestAgentNodeValidatorNoLlm:
    def test_agent_node_whose_agent_has_no_llm_names_the_agent_and_the_node(
        self, graph, default_org
    ):
        _agent_node(graph, "Writer", 2, agent=_agent(default_org, "Copywriter"))

        with pytest.raises(AgentNodeRunValidationError) as error:
            _validate_agent_nodes(graph)

        assert str(error.value.detail) == (
            'Agent "Copywriter" in Agent node "Writer #2" has no LLM. '
            "Choose one for the agent on the Agents page."
        )

    def test_task_node_whose_agent_has_no_llm_names_the_agent_and_the_node(
        self, graph, default_org
    ):
        _task_node(graph, "Summarize", 4, agent=_agent(default_org, "Copywriter"))

        with pytest.raises(AgentNodeRunValidationError) as error:
            _validate_agent_nodes(graph)

        assert str(error.value.detail) == (
            'Agent "Copywriter" in Task node "Summarize #4" has no LLM. '
            "Choose one for the agent on the Agents page."
        )

    def test_nodes_sharing_the_agent_are_named_in_one_sentence_agent_nodes_first(
        self, graph, default_org
    ):
        copywriter = _agent(default_org, "Copywriter")
        _task_node(graph, "Summarize", 3, agent=copywriter)
        _agent_node(graph, "Writer", 1, agent=copywriter)
        _agent_node(graph, "Rewriter", 2, agent=copywriter)

        with pytest.raises(AgentNodeRunValidationError) as error:
            _validate_agent_nodes(graph)

        assert str(error.value.detail) == (
            'Agent "Copywriter" in Agent nodes "Writer #1" and "Rewriter #2" and Task node '
            '"Summarize #3" has no LLM. Choose one for the agent on the Agents page.'
        )

    def test_agents_are_listed_in_the_order_of_the_first_node_using_them(
        self, graph, default_org
    ):
        reviewer = _agent(default_org, "Reviewer")
        copywriter = _agent(default_org, "Copywriter")
        _agent_node(graph, "Writer", 1, agent=copywriter)
        _agent_node(graph, "Checker", 2, agent=reviewer)
        _task_node(graph, "Summarize", 3, agent=copywriter)

        with pytest.raises(AgentNodeRunValidationError) as error:
            _validate_agent_nodes(graph)

        assert str(error.value.detail) == (
            'Agent "Copywriter" in Agent node "Writer #1" and Task node "Summarize #3" has no '
            'LLM. Agent "Reviewer" in Agent node "Checker #2" has no LLM. '
            "Choose one for each agent on the Agents page."
        )

    def test_shared_agent_inside_a_subflow_names_that_subflow_once(self, graph, default_org):
        copywriter = _agent(default_org, "Copywriter")
        _agent_node(graph, "Writer", 1, agent=copywriter)
        _task_node(graph, "Summarize", 2, agent=copywriter)

        with pytest.raises(AgentNodeRunValidationError) as error:
            _validate_agent_nodes(graph, flow_name="Invoice parser")

        assert str(error.value.detail) == (
            'Agent "Copywriter" in Agent node "Writer #1" and Task node "Summarize #2" in flow '
            '"Invoice parser" has no LLM. Choose one for the agent on the Agents page.'
        )

    def test_several_agents_without_an_llm_get_a_sentence_each(self, graph, default_org):
        _agent_node(graph, "Writer", 1, agent=_agent(default_org, "Copywriter"))
        _agent_node(graph, "Checker", 2, agent=_agent(default_org, "Reviewer"))

        with pytest.raises(AgentNodeRunValidationError) as error:
            _validate_agent_nodes(graph)

        assert str(error.value.detail) == (
            'Agent "Copywriter" in Agent node "Writer #1" has no LLM. '
            'Agent "Reviewer" in Agent node "Checker #2" has no LLM. '
            "Choose one for each agent on the Agents page."
        )

    def test_node_inside_a_subflow_names_that_subflow(self, graph, default_org):
        _task_node(graph, "Summarize", 4, agent=_agent(default_org, "Copywriter"))

        with pytest.raises(AgentNodeRunValidationError) as error:
            _validate_agent_nodes(graph, flow_name="Invoice parser")

        assert str(error.value.detail) == (
            'Agent "Copywriter" in Task node "Summarize #4" in flow "Invoice parser" has no '
            "LLM. Choose one for the agent on the Agents page."
        )

    def test_missing_llm_is_reported_before_missing_tasks(self, graph, default_org, llm_config):
        lead = _agent(default_org, "Lead", llm_config)
        _agent_node(graph, "Planner", 1, agent=lead, task_count=0)
        _task_node(graph, "Summarize", 2, agent=_agent(default_org, "Copywriter"))

        with pytest.raises(AgentNodeRunValidationError) as error:
            _validate_agent_nodes(graph)

        assert str(error.value.detail) == (
            'Agent "Copywriter" in Task node "Summarize #2" has no LLM. '
            "Choose one for the agent on the Agents page."
        )


@pytest.mark.django_db
class TestAgentNodeValidatorNoTasks:
    @pytest.fixture
    def copywriter(self, default_org, llm_config) -> AgentDefinition:
        return _agent(default_org, "Copywriter", llm_config)

    def test_agent_node_without_tasks_is_named(self, graph, copywriter):
        _agent_node(graph, "Writer", 2, agent=copywriter, task_count=0)

        with pytest.raises(AgentNodeRunValidationError) as error:
            _validate_agent_nodes(graph)

        assert str(error.value.detail) == (
            'Agent node "Writer #2" has no tasks. Add at least one task.'
        )

    def test_several_agent_nodes_without_tasks_are_listed(self, graph, copywriter):
        _agent_node(graph, "A", 1, agent=copywriter, task_count=0)
        _agent_node(graph, "B", 2, agent=copywriter, task_count=0)
        _agent_node(graph, "C", 3, agent=copywriter)

        with pytest.raises(AgentNodeRunValidationError) as error:
            _validate_agent_nodes(graph)

        assert str(error.value.detail) == (
            'Agent nodes "A #1" and "B #2" have no tasks. Add at least one task to each.'
        )

    def test_node_inside_a_subflow_names_that_subflow(self, graph, copywriter):
        _agent_node(graph, "Writer", 2, agent=copywriter, task_count=0)

        with pytest.raises(AgentNodeRunValidationError) as error:
            _validate_agent_nodes(graph, flow_name="Invoice parser")

        assert str(error.value.detail) == (
            'Agent node "Writer #2" in flow "Invoice parser" has no tasks. '
            "Add at least one task."
        )

    def test_set_up_agent_and_task_nodes_pass(self, graph, copywriter):
        _agent_node(graph, "Writer", 1, agent=copywriter)
        _task_node(graph, "Summarize", 2, agent=copywriter)

        _validate_agent_nodes(graph)


@pytest.mark.django_db
class TestKeyValueNodeValidator:
    @staticmethod
    def _validate(graph, flow_name: str | None = None) -> None:
        KeyValueNodeValidator().validate_runnable(
            KeyValueNode.objects.filter(graph=graph).order_by("node_number", "id"),
            flow_name=flow_name,
        )

    def test_node_without_a_table_is_named(self, graph):
        KeyValueNode.objects.create(graph=graph, node_name="Save lead", node_number=3)

        with pytest.raises(KeyValueNodeRunValidationError) as error:
            self._validate(graph)

        assert str(error.value.detail) == 'Key-Value node "Save lead #3" has no table selected.'

    def test_several_nodes_without_a_table_are_listed(self, graph, default_org):
        KeyValueNode.objects.create(graph=graph, node_name="Save lead", node_number=1)
        KeyValueNode.objects.create(graph=graph, node_name="Load lead", node_number=2)
        KeyValueNode.objects.create(
            graph=graph,
            node_name="Kept",
            node_number=3,
            key_value_table=KeyValueTable.objects.create(org=default_org, name="Leads"),
        )

        with pytest.raises(KeyValueNodeRunValidationError) as error:
            self._validate(graph)

        assert str(error.value.detail) == (
            'Key-Value nodes "Save lead #1" and "Load lead #2" have no table selected.'
        )

    def test_node_inside_a_subflow_names_that_subflow(self, graph):
        KeyValueNode.objects.create(graph=graph, node_name="Save lead", node_number=3)

        with pytest.raises(KeyValueNodeRunValidationError) as error:
            self._validate(graph, flow_name="Invoice parser")

        assert str(error.value.detail) == (
            'Key-Value node "Save lead #3" in flow "Invoice parser" has no table selected.'
        )

    def test_node_with_a_table_passes(self, graph, default_org):
        KeyValueNode.objects.create(
            graph=graph,
            node_name="Save lead",
            key_value_table=KeyValueTable.objects.create(org=default_org, name="Leads"),
        )

        self._validate(graph)


# Any id: the validators don't look at the node a condition or an error route leads to.
NEXT_NODE_ID = 9001


def _decision_table(
    graph, name: str, number: int, *, next_error_node_id: int | None = None
) -> DecisionTableNode:
    return DecisionTableNode.objects.create(
        graph=graph, node_name=name, node_number=number, next_error_node_id=next_error_node_id
    )


def _complex_condition(
    table: DecisionTableNode,
    name: str,
    *,
    order: int = 0,
    expression: str | None = "variables.score > 5",
    next_node_id: int | None = NEXT_NODE_ID,
) -> ConditionGroup:
    return ConditionGroup.objects.create(
        decision_table_node=table,
        group_name=name,
        group_type="complex",
        order=order,
        expression=expression,
        next_node_id=next_node_id,
    )


def _simple_condition(
    table: DecisionTableNode, name: str, condition_texts: list[str]
) -> ConditionGroup:
    group = ConditionGroup.objects.create(
        decision_table_node=table,
        group_name=name,
        group_type="simple",
        next_node_id=NEXT_NODE_ID,
    )
    for order, text in enumerate(condition_texts):
        Condition.objects.create(
            condition_group=group, condition_name=f"Check {order}", order=order, condition=text
        )
    return group


def _validate_decision_tables(graph, flow_name: str | None = None) -> None:
    DecisionTableNodeValidator().validate_runnable(
        DecisionTableNode.objects.filter(graph=graph)
        .prefetch_related("condition_groups__conditions")
        .order_by("node_number", "id"),
        flow_name=flow_name,
    )


def _decision_table_error(graph, flow_name: str | None = None) -> str:
    with pytest.raises(DecisionTableNodeRunValidationError) as error:
        _validate_decision_tables(graph, flow_name)
    return str(error.value.detail)


@pytest.mark.django_db
class TestDecisionTableNodeValidator:
    @pytest.mark.parametrize(
        "make_table",
        [
            pytest.param(lambda table: None, id="no-conditions"),
            pytest.param(
                lambda table: _complex_condition(table, "High score", next_node_id=None),
                id="condition-without-a-next-node",
            ),
            pytest.param(
                lambda table: ConditionGroup.objects.filter(
                    pk=_complex_condition(table, "High score", expression="  ").pk
                ).update(active=False, soft_deleted_at=timezone.now()),
                id="condition-with-a-blank-expression-in-the-recycle-bin",
            ),
            pytest.param(
                lambda table: _complex_condition(table, "High score", expression=None),
                id="complex-condition-without-an-expression",
            ),
            pytest.param(
                lambda table: _simple_condition(table, "High score", []),
                id="simple-condition-without-conditions",
            ),
        ],
    )
    def test_table_crew_runs_without_failing_runs(self, graph, make_table):
        make_table(_decision_table(graph, "Route", 4))

        _validate_decision_tables(graph)

    @pytest.mark.parametrize("expression", ["", "   "], ids=["empty", "blank"])
    def test_complex_condition_with_a_blank_expression_is_named(self, graph, expression):
        _complex_condition(_decision_table(graph, "Route", 4), "High score", expression=expression)

        assert _decision_table_error(graph) == (
            'Condition "High score" in Decision Table node "Route #4" has no expression.'
        )

    @pytest.mark.parametrize(
        "condition_texts",
        [["  "], ["x > 1", "  "]],
        ids=["only-blank-conditions", "one-blank-condition"],
    )
    def test_simple_condition_with_a_blank_condition_has_no_expression(
        self, graph, condition_texts
    ):
        _simple_condition(_decision_table(graph, "Route", 4), "High score", condition_texts)

        assert _decision_table_error(graph) == (
            'Condition "High score" in Decision Table node "Route #4" has no expression.'
        )

    def test_conditions_with_blank_expressions_get_a_sentence_per_node_in_table_order(self, graph):
        route = _decision_table(graph, "Route", 1)
        _complex_condition(route, "Low score", order=2, expression="")
        _complex_condition(route, "High score", order=1, expression="")
        _complex_condition(route, "Kept", order=3)
        _complex_condition(_decision_table(graph, "Triage", 2), "Urgent", expression="")

        assert _decision_table_error(graph) == (
            'Conditions "High score" and "Low score" in Decision Table node "Route #1" have no '
            'expression. Condition "Urgent" in Decision Table node "Triage #2" has no expression.'
        )

    def test_node_inside_a_subflow_names_that_subflow(self, graph):
        _complex_condition(_decision_table(graph, "Route", 4), "High score", expression="")

        assert _decision_table_error(graph, flow_name="Invoice parser") == (
            'Condition "High score" in Decision Table node "Route #4" in flow '
            '"Invoice parser" has no expression.'
        )

    @pytest.mark.parametrize(
        "make_condition",
        [
            pytest.param(
                lambda table: _complex_condition(table, "High score", expression=" "),
                id="blank-expression",
            ),
            pytest.param(
                lambda table: _simple_condition(table, "High score", ["x > 1", " "]),
                id="blank-condition",
            ),
        ],
    )
    def test_node_with_an_error_route_is_not_checked(self, graph, make_condition):
        make_condition(_decision_table(graph, "Route", 4, next_error_node_id=NEXT_NODE_ID))

        _validate_decision_tables(graph)

    def test_set_up_simple_and_complex_conditions_pass(self, graph):
        route = _decision_table(graph, "Route", 4)
        _complex_condition(route, "High score", order=1)
        _simple_condition(route, "Low score", ["variables.score < 2"])

        _validate_decision_tables(graph)


def _classification_table(
    graph,
    name: str,
    number: int,
    *,
    default_llm_config: LLMConfig | None = None,
    next_error_node_id: int | None = None,
) -> ClassificationDecisionTableNode:
    return ClassificationDecisionTableNode.objects.create(
        graph=graph,
        node_name=name,
        node_number=number,
        default_llm_config=default_llm_config,
        next_error_node_id=next_error_node_id,
    )


def _prompt(
    table: ClassificationDecisionTableNode, key: str, llm_config: LLMConfig | None = None
) -> ClassificationDecisionTablePrompt:
    return ClassificationDecisionTablePrompt.objects.create(
        cdt_node=table, prompt_key=key, llm_config=llm_config
    )


def _row(
    table: ClassificationDecisionTableNode,
    name: str,
    prompt: ClassificationDecisionTablePrompt | None,
    *,
    order: int = 0,
    enabled: bool = True,
) -> ClassificationConditionGroup:
    return ClassificationConditionGroup.objects.create(
        classification_decision_table_node=table,
        group_name=name,
        order=order,
        prompt=prompt,
        dock_visible=enabled,
    )


def _bin(prompt: ClassificationDecisionTablePrompt) -> None:
    ClassificationDecisionTablePrompt.objects.filter(pk=prompt.pk).update(
        active=False, soft_deleted_at=timezone.now()
    )


def _validate_classification_tables(graph, flow_name: str | None = None) -> None:
    ClassificationDecisionTableNodeValidator().validate_runnable(
        ClassificationDecisionTableNode.objects.filter(graph=graph)
        .select_related("default_llm_config__model")
        .prefetch_related("condition_groups__prompt", "prompt_configs__llm_config__model")
        .order_by("node_number", "id"),
        flow_name=flow_name,
    )


def _classification_table_error(graph, flow_name: str | None = None) -> str:
    with pytest.raises(ClassificationDecisionTableNodeRunValidationError) as error:
        _validate_classification_tables(graph, flow_name)
    return str(error.value.detail)


@pytest.fixture
def llm_config_without_model(default_org) -> LLMConfig:
    return LLMConfig.objects.create(custom_name="Unfinished", model=None, org=default_org)


@pytest.mark.django_db
class TestClassificationDecisionTableNodeValidatorNoLlm:
    def test_used_prompt_without_an_llm_or_a_default_is_named(self, graph):
        table = _classification_table(graph, "Route", 4)
        _row(table, "High score", _prompt(table, "classify"))

        assert _classification_table_error(graph) == (
            'Prompt "classify" in Classification Table node "Route #4" has no LLM. '
            "Choose one for it, or set a default LLM for the node."
        )

    def test_prompt_whose_llm_has_no_model_does_not_fall_back_to_the_default(
        self, graph, llm_config, llm_config_without_model
    ):
        table = _classification_table(graph, "Route", 4, default_llm_config=llm_config)
        _row(table, "High score", _prompt(table, "classify", llm_config_without_model))

        assert _classification_table_error(graph) == (
            'Prompt "classify" in Classification Table node "Route #4" has no LLM. '
            "Choose one for it, or set a default LLM for the node."
        )

    def test_default_llm_without_a_model_counts_as_none(self, graph, llm_config_without_model):
        table = _classification_table(
            graph, "Route", 4, default_llm_config=llm_config_without_model
        )
        _row(table, "High score", _prompt(table, "classify"))

        assert _classification_table_error(graph) == (
            'Prompt "classify" in Classification Table node "Route #4" has no LLM. '
            "Choose one for it, or set a default LLM for the node."
        )

    def test_prompts_of_one_node_share_a_sentence_in_the_order_rows_use_them(self, graph):
        table = _classification_table(graph, "Route", 4)
        summarize = _prompt(table, "summarize")
        classify = _prompt(table, "classify")
        _row(table, "Low score", summarize, order=2)
        _row(table, "High score", classify, order=1)
        _row(table, "Again", classify, order=3)

        assert _classification_table_error(graph) == (
            'Prompts "classify" and "summarize" in Classification Table node "Route #4" have no '
            "LLM. Choose one for each, or set a default LLM for the node."
        )

    def test_several_nodes_get_a_sentence_each(self, graph):
        route = _classification_table(graph, "Route", 1)
        _row(route, "High score", _prompt(route, "classify"))
        triage = _classification_table(graph, "Triage", 2)
        _row(triage, "Urgent", _prompt(triage, "detect"))

        assert _classification_table_error(graph) == (
            'Prompt "classify" in Classification Table node "Route #1" has no LLM. '
            'Prompt "detect" in Classification Table node "Triage #2" has no LLM. '
            "Choose one for each, or set a default LLM for each node."
        )

    def test_node_inside_a_subflow_names_that_subflow(self, graph):
        table = _classification_table(graph, "Route", 4)
        _row(table, "High score", _prompt(table, "classify"))

        assert _classification_table_error(graph, flow_name="Invoice parser") == (
            'Prompt "classify" in Classification Table node "Route #4" in flow '
            '"Invoice parser" has no LLM. Choose one for it, or set a default LLM for the node.'
        )

    def test_prompts_crew_never_runs_are_not_checked(self, graph):
        table = _classification_table(graph, "Route", 4)
        _prompt(table, "unused")
        _row(table, "Disabled", _prompt(table, "classify"), enabled=False)
        _row(table, "No prompt", None)

        _validate_classification_tables(graph)

    def test_node_with_an_error_route_is_not_checked(self, graph):
        table = _classification_table(graph, "Route", 4, next_error_node_id=NEXT_NODE_ID)
        _row(table, "High score", _prompt(table, "classify"))

        _validate_classification_tables(graph)

    def test_row_using_a_prompt_in_the_recycle_bin_runs(self, graph):
        # Crew skips a prompt it wasn't sent, so a binned one without an LLM runs too.
        table = _classification_table(graph, "Route", 4)
        prompt = _prompt(table, "classify")
        _row(table, "High score", prompt)
        _bin(prompt)

        _validate_classification_tables(graph)

    def test_prompt_with_its_own_llm_or_the_node_default_passes(self, graph, llm_config):
        with_default = _classification_table(graph, "Route", 1, default_llm_config=llm_config)
        _row(with_default, "High score", _prompt(with_default, "classify"))
        with_own_llm = _classification_table(graph, "Triage", 2)
        _row(with_own_llm, "Urgent", _prompt(with_own_llm, "detect", llm_config))

        _validate_classification_tables(graph)


def _subflow_node(graph, input_map, *, name="Run B", number=1, output_variable_path=None):
    return SubGraphNode.objects.create(
        graph=graph,
        node_name=name,
        node_number=number,
        input_map=input_map,
        output_variable_path=output_variable_path,
    )


def _validate_subflow_nodes(graph, flow_name: str | None = None) -> None:
    SubGraphNodeValidator().validate_runnable(
        SubGraphNode.objects.filter(graph=graph).order_by("node_number", "id"),
        flow_name=flow_name,
    )


@pytest.mark.django_db
class TestSubGraphNodeValidator:
    @pytest.mark.parametrize(
        "value",
        [
            "customer",
            "variablescustomer",
            "variables_customer",
            "",
            "   ",
            "|fallback",
            "customer|variables.customer",
            "[0].variables",
            42,
            None,
            True,
            ["variables.customer"],
            {"path": "variables.customer"},
        ],
        ids=[
            "plain-name",
            "prefix-without-separator",
            "prefix-joined-by-underscore",
            "empty",
            "blank",
            "only-a-default",
            "variable-only-in-the-default",
            "index-before-variables",
            "number",
            "null",
            "boolean",
            "list",
            "object",
        ],
    )
    def test_input_crew_cannot_read_is_refused_with_its_fix(self, graph, value):
        _subflow_node(graph, {"customer": value})

        with pytest.raises(SubGraphNodeRunValidationError) as error:
            _validate_subflow_nodes(graph)

        assert str(error.value.detail) == (
            'Input "customer" of Subflow node "Run B #1" must be a flow variable, '
            "like variables.customer."
        )

    @pytest.mark.parametrize(
        "value",
        [
            "variables",
            "variables.customer",
            "variables.customer.name",
            "variables.items[0]",
            "variables[0]",
            "variables.customer|nobody",
            "variables.customer|",
            "  variables.customer",
            "{variables.customer}",
            "$variables.customer",
            "variables-customer",
        ],
    )
    def test_input_crew_reads_runs(self, graph, value):
        _subflow_node(graph, {"customer": value})

        _validate_subflow_nodes(graph)

    @pytest.mark.parametrize(
        "output_variable_path",
        ["result", "variables", "variables.result", "results[0]", "-", ""],
    )
    def test_any_output_path_runs_since_crew_stores_every_one(self, graph, output_variable_path):
        _subflow_node(graph, {}, output_variable_path=output_variable_path)

        _validate_subflow_nodes(graph)

    def test_map_that_is_not_an_object_is_left_to_the_session_build(self, graph):
        _subflow_node(graph, ["customer"])

        _validate_subflow_nodes(graph)

    def test_first_input_by_name_of_the_first_node_is_named(self, graph):
        _subflow_node(graph, {"zip": "zip"}, name="Run C", number=2)
        _subflow_node(
            graph,
            {"order": "variables.order", "customer": "customer", "amount": "amount"},
            name="Run B",
            number=1,
        )

        with pytest.raises(SubGraphNodeRunValidationError) as error:
            _validate_subflow_nodes(graph)

        assert str(error.value.detail) == (
            'Input "amount" of Subflow node "Run B #1" must be a flow variable, '
            "like variables.amount."
        )

    def test_node_inside_a_subflow_names_that_subflow(self, graph):
        _subflow_node(graph, {"customer": "customer"})

        with pytest.raises(SubGraphNodeRunValidationError) as error:
            _validate_subflow_nodes(graph, flow_name="Invoice parser")

        assert str(error.value.detail) == (
            'Input "customer" of Subflow node "Run B #1" in flow "Invoice parser" must be a '
            "flow variable, like variables.customer."
        )

    def test_node_without_inputs_runs(self, graph):
        _subflow_node(graph, {})

        _validate_subflow_nodes(graph)
