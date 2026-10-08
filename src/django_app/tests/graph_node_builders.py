"""Build rows of every exported graph node model with only their required fields set."""

from itertools import count

from tables.import_export.strategies.nodes.node_maps import NODE_RELATIONS
from tables.models import Graph, PythonCode
from tables.models.graph_models import (
    EndNode,
    GraphNote,
    PythonNode,
    StartNode,
    WebhookTriggerNode,
)

NODE_MODELS = tuple(
    Graph._meta.get_field(relation).related_model for relation in NODE_RELATIONS.values()
)

# Start and End nodes have their own one-per-graph constraint.
MULTIPLE_PER_GRAPH_NODE_MODELS = tuple(
    model for model in NODE_MODELS if model not in (StartNode, EndNode)
)

_node_numbers = count(1)


def node_fields(model) -> dict:
    """Return the fields a new row of `model` needs, apart from its graph."""
    if model is StartNode:
        return {"variables": {}}
    if model is EndNode:
        return {"output_map": {"context": "variables"}}
    if model is GraphNote:
        return {"content": "note"}
    fields = {"node_name": f"{model.__name__}-{next(_node_numbers)}"}
    if model in (PythonNode, WebhookTriggerNode):
        fields["python_code"] = PythonCode.objects.create(code="def main(): ...")
    return fields


def create_node(model, graph: Graph, **overrides):
    return model.objects.create(graph=graph, **{**node_fields(model), **overrides})
