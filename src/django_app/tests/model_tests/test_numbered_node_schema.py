import pytest

from tables.models import (
    AgentNode,
    ClassificationDecisionTableNode,
    DecisionTableNode,
    EndNode,
    Graph,
    GraphNote,
    PythonCode,
    PythonNode,
    ScheduleTriggerNode,
    StartNode,
    TelegramTriggerNode,
    WebhookTriggerNode,
)
from tables.services.node_number_service import NodeNumberService

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


def _stored_counter(graph) -> int:
    return Graph.all_objects.values_list("node_number_seq", flat=True).get(pk=graph.pk)


# Graph.save() on an instance loaded before numbers were issued must not lower the counter,
# or the next node would be given a number a live node already holds.
@pytest.mark.django_db
@pytest.mark.parametrize(
    "save_kwargs",
    [
        pytest.param({}, id="full-save"),
        pytest.param({"update_fields": ["name", "node_number_seq"]}, id="update-fields-naming-the-counter"),
    ],
)
def test_saving_a_stale_graph_instance_keeps_the_issued_counter(graph, save_kwargs):
    stale_graph = Graph.objects.get(pk=graph.pk)
    NodeNumberService().reserve(graph.pk, 3)

    stale_graph.name = "renamed"
    stale_graph.save(**save_kwargs)

    assert _stored_counter(graph) == 3
    assert Graph.objects.get(pk=graph.pk).name == "renamed"


@pytest.mark.django_db
def test_node_created_after_a_stale_graph_save_gets_a_fresh_number(graph):
    stale_graph = Graph.objects.get(pk=graph.pk)
    first = PythonNode.objects.create(
        graph=graph, python_code=PythonCode.objects.create(code="def main(): return None")
    )

    stale_graph.description = "edited"
    stale_graph.save()
    second = PythonNode.objects.create(
        graph=graph, python_code=PythonCode.objects.create(code="def main(): return None")
    )

    assert (first.node_number, second.node_number) == (1, 2)
