import pytest

from tables.models.graph_models import Graph, GraphOrganization
from tables.services.converter_service import ConverterService


@pytest.mark.django_db
def test_org_prefix_derives_from_graph_org(default_org):
    graph = Graph.objects.create(name="prefix", org=default_org)
    GraphOrganization.objects.create(graph=graph)
    prefix = ConverterService()._resolve_org_prefix_for_graph(graph.id)
    assert prefix == f"org_{default_org.id}"


@pytest.mark.django_db
def test_org_prefix_none_for_missing_graph():
    assert ConverterService()._resolve_org_prefix_for_graph(999999) is None
