import pytest

from tables.models import (
    AgentNode,
    ClassificationDecisionTableNode,
    DecisionTableNode,
    EndNode,
    GraphNote,
    PythonCode,
    PythonNode,
    ScheduleTriggerNode,
    StartNode,
    TelegramTriggerNode,
    WebhookTriggerNode,
)

HASHED_NODE_BUILDERS = {
    "agent": lambda graph: AgentNode.objects.create(graph=graph),
    "python": lambda graph: PythonNode.objects.create(
        graph=graph, python_code=PythonCode.objects.create(code="def main(): return None")
    ),
    "decision_table": lambda graph: DecisionTableNode.objects.create(
        graph=graph, node_name="decision"
    ),
    "webhook_trigger": lambda graph: WebhookTriggerNode.objects.create(
        graph=graph,
        node_name="webhook",
        python_code=PythonCode.objects.create(code="def main(): return None"),
    ),
    "telegram_trigger": lambda graph: TelegramTriggerNode.objects.create(
        graph=graph, node_name="telegram"
    ),
    "schedule_trigger": lambda graph: ScheduleTriggerNode.objects.create(
        graph=graph, node_name="schedule"
    ),
}


@pytest.mark.parametrize("model", [StartNode, EndNode, GraphNote])
def test_structural_nodes_have_no_node_number(model):
    assert "node_number" not in {field.name for field in model._meta.get_fields()}


@pytest.mark.django_db
def test_new_python_node_gets_the_first_number(graph):
    node = HASHED_NODE_BUILDERS["python"](graph)

    node.refresh_from_db()

    assert node.node_number == 1


@pytest.mark.django_db
def test_graph_counter_defaults_to_zero(graph):
    assert graph.node_number_seq == 0


@pytest.mark.django_db
def test_two_cdt_nodes_may_share_a_name(graph):
    ClassificationDecisionTableNode.objects.create(graph=graph, node_name="Router")
    ClassificationDecisionTableNode.objects.create(graph=graph, node_name="Router")

    router_count = ClassificationDecisionTableNode.objects.filter(
        graph=graph, node_name="Router"
    ).count()
    assert router_count == 2


@pytest.mark.django_db
@pytest.mark.parametrize("node_kind", list(HASHED_NODE_BUILDERS))
def test_renumbering_a_node_does_not_change_its_content_hash(graph, node_kind):
    node = HASHED_NODE_BUILDERS[node_kind](graph)
    hash_before = node.content_hash

    node.node_number = 7
    node.save()
    node.refresh_from_db()

    assert node.node_number == 7
    assert node.content_hash == hash_before
