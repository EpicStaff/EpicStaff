"""Building a flow's GraphData costs the same queries for one Classification Table as for two.

The run checks and the converter read each node's default LLM, its prompts with their
LLMs, and its rows with their prompts. Those reads come from the prefetches in
`SessionManagerService._build_graph_data`; without one, every node would cost queries.
Comparing a flow with one node against a flow with two keeps the test about this, not
about the other node lists the method loads.
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from tables.models import Edge, StartNode
from tables.models.graph_models import (
    ClassificationConditionGroup,
    ClassificationDecisionTableNode,
    ClassificationDecisionTablePrompt,
    Graph,
)
from tables.services.session_manager_service import SessionManagerService


def _flow_with_classification_tables(org, llm_config, node_count: int) -> Graph:
    """A flow whose Start leads to `node_count` Classification Tables.

    Each table has a default LLM, a prompt with its own LLM, a prompt that falls back
    to the default, and a row using each prompt.
    """
    graph = Graph.objects.create(name=f"flow with {node_count}", org=org)
    start_node = StartNode.objects.create(graph=graph, variables={})
    for number in range(1, node_count + 1):
        table = ClassificationDecisionTableNode.objects.create(
            graph=graph,
            node_name="Route",
            node_number=number,
            default_llm_config=llm_config,
        )
        own_llm_prompt = ClassificationDecisionTablePrompt.objects.create(
            cdt_node=table, prompt_key="classify", llm_config=llm_config
        )
        default_llm_prompt = ClassificationDecisionTablePrompt.objects.create(
            cdt_node=table, prompt_key="summarize"
        )
        for order, prompt in enumerate((own_llm_prompt, default_llm_prompt)):
            ClassificationConditionGroup.objects.create(
                classification_decision_table_node=table,
                group_name=f"Row {order}",
                order=order,
                prompt=prompt,
            )
        Edge.objects.create(graph=graph, start_node_id=start_node.id, end_node_id=table.id)
    return graph


def _queries_to_build(graph: Graph) -> int:
    start_node = StartNode.objects.get(graph=graph)
    with CaptureQueriesContext(connection) as captured:
        graph_data = SessionManagerService()._build_graph_data(
            graph, None, None, start_node=start_node
        )
    assert len(graph_data.classification_decision_table_node_list) == (
        ClassificationDecisionTableNode.objects.filter(graph=graph).count()
    )
    return len(captured.captured_queries)


@pytest.mark.django_db
def test_a_second_classification_table_costs_no_queries(default_org, llm_config):
    one_table = _flow_with_classification_tables(default_org, llm_config, node_count=1)
    two_tables = _flow_with_classification_tables(default_org, llm_config, node_count=2)

    assert _queries_to_build(two_tables) == _queries_to_build(one_table)
