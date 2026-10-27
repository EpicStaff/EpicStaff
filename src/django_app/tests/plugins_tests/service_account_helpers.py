"""Rows the service-account tests act on."""

from tables.models import Graph, PythonCode, StartNode
from tables.models.graph_models import Edge, PythonNode


def runnable_graph(name, organization):
    """A flow with a start node and one Python node, ready to run."""
    graph = Graph.objects.create(name=name, org=organization)
    start = StartNode.objects.create(graph=graph, variables={})
    python_code = PythonCode.objects.create(code="def main(**kwargs):\n    return None\n", entrypoint="main")
    node = PythonNode.objects.create(graph=graph, python_code=python_code, node_name="py_node")
    Edge.objects.create(graph=graph, start_node_id=start.pk, end_node_id=node.pk)
    return graph
