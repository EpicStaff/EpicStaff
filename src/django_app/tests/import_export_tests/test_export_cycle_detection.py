"""Cycle detection in graph export dependencies: ExportCycleError (400)."""

import pytest
from django.urls import reverse

from rbac.models import Organization
from tables.exceptions import ExportCycleError
from tables.import_export.enums import EntityType
from tables.import_export.registry import entity_registry
from tables.import_export.services.export_service import DependencyCollector, ExportService
from tables.models import Graph, StartNode, SubGraphNode
from tests.helpers import UNRESTRICTED_EXPORT_POLICY


@pytest.mark.django_db
class TestDependencyCollectorCycleDetection:
    def test_detects_cycle_not_containing_root(self, default_org):
        """A → B → C → B: cycle does not contain the exported root A."""
        graph_a = Graph.objects.create(name="A", metadata={"nodes": [], "edges": []}, org=default_org)
        graph_b = Graph.objects.create(name="B", metadata={"nodes": [], "edges": []}, org=default_org)
        graph_c = Graph.objects.create(name="C", metadata={"nodes": [], "edges": []}, org=default_org)

        StartNode.objects.create(graph=graph_a, variables={})
        StartNode.objects.create(graph=graph_b, variables={})
        StartNode.objects.create(graph=graph_c, variables={})

        SubGraphNode.objects.create(graph=graph_a, node_name="subgraph_b", subgraph=graph_b)
        SubGraphNode.objects.create(graph=graph_b, node_name="subgraph_c", subgraph=graph_c)
        SubGraphNode.objects.create(graph=graph_c, node_name="subgraph_b", subgraph=graph_b)

        collector = DependencyCollector(entity_registry, policy=UNRESTRICTED_EXPORT_POLICY)

        with pytest.raises(ExportCycleError) as exc_info:
            collector.collect(EntityType.GRAPH, graph_a.id)

        cycle_error = exc_info.value
        assert cycle_error.status_code == 400
        assert cycle_error.default_code == "export_cycle_detected"
        assert cycle_error.cycle_path == [
            (EntityType.GRAPH, graph_b.id),
            (EntityType.GRAPH, graph_c.id),
            (EntityType.GRAPH, graph_b.id),
        ]

    def test_detects_self_loop(self, default_org):
        graph_a = Graph.objects.create(name="A", metadata={"nodes": [], "edges": []}, org=default_org)
        StartNode.objects.create(graph=graph_a, variables={})
        SubGraphNode.objects.create(graph=graph_a, node_name="self_ref", subgraph=graph_a)

        collector = DependencyCollector(entity_registry, policy=UNRESTRICTED_EXPORT_POLICY)

        with pytest.raises(ExportCycleError) as exc_info:
            collector.collect(EntityType.GRAPH, graph_a.id)

        cycle_error = exc_info.value
        assert cycle_error.status_code == 400
        assert cycle_error.cycle_path == [(EntityType.GRAPH, graph_a.id)] * 2

    def test_diamond_export_unchanged(self, default_org):
        """A → {B, C} → D: no cycle, D reached twice via different branches."""
        graph_a = Graph.objects.create(name="A", metadata={"nodes": [], "edges": []}, org=default_org)
        graph_b = Graph.objects.create(name="B", metadata={"nodes": [], "edges": []}, org=default_org)
        graph_c = Graph.objects.create(name="C", metadata={"nodes": [], "edges": []}, org=default_org)
        graph_d = Graph.objects.create(name="D", metadata={"nodes": [], "edges": []}, org=default_org)

        for g in [graph_a, graph_b, graph_c, graph_d]:
            StartNode.objects.create(graph=g, variables={})

        SubGraphNode.objects.create(graph=graph_a, node_name="sub_b", subgraph=graph_b)
        SubGraphNode.objects.create(graph=graph_a, node_name="sub_c", subgraph=graph_c)
        SubGraphNode.objects.create(graph=graph_b, node_name="sub_d", subgraph=graph_d)
        SubGraphNode.objects.create(graph=graph_c, node_name="sub_d", subgraph=graph_d)

        collector = DependencyCollector(entity_registry, policy=UNRESTRICTED_EXPORT_POLICY)
        collector.collect(EntityType.GRAPH, graph_a.id)

        assert set(collector.collected[EntityType.GRAPH]) == {
            graph_a.id,
            graph_b.id,
            graph_c.id,
            graph_d.id,
        }

    def test_shared_dependency_exported_once(self, default_org):
        graph_a = Graph.objects.create(name="A", metadata={"nodes": [], "edges": []}, org=default_org)
        graph_b = Graph.objects.create(name="B", metadata={"nodes": [], "edges": []}, org=default_org)
        graph_c = Graph.objects.create(name="C", metadata={"nodes": [], "edges": []}, org=default_org)
        graph_d = Graph.objects.create(name="D", metadata={"nodes": [], "edges": []}, org=default_org)

        for g in [graph_a, graph_b, graph_c, graph_d]:
            StartNode.objects.create(graph=g, variables={})

        SubGraphNode.objects.create(graph=graph_a, node_name="sub_b", subgraph=graph_b)
        SubGraphNode.objects.create(graph=graph_a, node_name="sub_c", subgraph=graph_c)
        SubGraphNode.objects.create(graph=graph_b, node_name="sub_d", subgraph=graph_d)
        SubGraphNode.objects.create(graph=graph_c, node_name="sub_d", subgraph=graph_d)

        collector = DependencyCollector(entity_registry, policy=UNRESTRICTED_EXPORT_POLICY)
        collector.collect(EntityType.GRAPH, graph_a.id)

        export_dict = collector.to_dict()
        exported_ids = [g["id"] for g in export_dict[EntityType.GRAPH]]
        assert exported_ids.count(graph_d.id) == 1


@pytest.mark.django_db
class TestExportCycleDetectionAPI:
    def test_cycle_returns_400_with_cycle_description(self, auth_client, default_org):
        graph_a = Graph.objects.create(name="A", metadata={"nodes": [], "edges": []}, org=default_org)
        graph_b = Graph.objects.create(name="B", metadata={"nodes": [], "edges": []}, org=default_org)
        graph_c = Graph.objects.create(name="C", metadata={"nodes": [], "edges": []}, org=default_org)

        for g in [graph_a, graph_b, graph_c]:
            StartNode.objects.create(graph=g, variables={})

        SubGraphNode.objects.create(graph=graph_a, node_name="sub_b", subgraph=graph_b)
        SubGraphNode.objects.create(graph=graph_b, node_name="sub_c", subgraph=graph_c)
        SubGraphNode.objects.create(graph=graph_c, node_name="sub_b", subgraph=graph_b)

        response = auth_client.get(reverse("graphs-export", kwargs={"pk": graph_a.id}))

        assert response.status_code == 400
        assert response.data["code"] == "export_cycle_detected"
        assert "Cycle detected" in response.data["message"]

    def test_diamond_export_via_api_succeeds(self, auth_client, default_org):
        graph_a = Graph.objects.create(name="A", metadata={"nodes": [], "edges": []}, org=default_org)
        graph_b = Graph.objects.create(name="B", metadata={"nodes": [], "edges": []}, org=default_org)
        graph_c = Graph.objects.create(name="C", metadata={"nodes": [], "edges": []}, org=default_org)
        graph_d = Graph.objects.create(name="D", metadata={"nodes": [], "edges": []}, org=default_org)

        for g in [graph_a, graph_b, graph_c, graph_d]:
            StartNode.objects.create(graph=g, variables={})

        SubGraphNode.objects.create(graph=graph_a, node_name="sub_b", subgraph=graph_b)
        SubGraphNode.objects.create(graph=graph_a, node_name="sub_c", subgraph=graph_c)
        SubGraphNode.objects.create(graph=graph_b, node_name="sub_d", subgraph=graph_d)
        SubGraphNode.objects.create(graph=graph_c, node_name="sub_d", subgraph=graph_d)

        response = auth_client.get(reverse("graphs-export", kwargs={"pk": graph_a.id}))

        assert response.status_code == 200
        assert len(response.json()[EntityType.GRAPH]) == 4

    def test_self_loop_returns_400(self, auth_client, default_org):
        graph_a = Graph.objects.create(name="A", metadata={"nodes": [], "edges": []}, org=default_org)
        StartNode.objects.create(graph=graph_a, variables={})
        SubGraphNode.objects.create(graph=graph_a, node_name="self", subgraph=graph_a)

        response = auth_client.get(reverse("graphs-export", kwargs={"pk": graph_a.id}))

        assert response.status_code == 400
        assert response.data["code"] == "export_cycle_detected"

    def test_cross_org_export_returns_404_before_cycle_check(self, auth_client, default_org):
        """auth_client (default_org) must get 404 on a cyclic graph in another org, not 400."""
        other_org = Organization.objects.create(name="Other Org")

        graph_a = Graph.objects.create(name="A", metadata={"nodes": [], "edges": []}, org=other_org)
        graph_b = Graph.objects.create(name="B", metadata={"nodes": [], "edges": []}, org=other_org)
        graph_c = Graph.objects.create(name="C", metadata={"nodes": [], "edges": []}, org=other_org)

        for g in [graph_a, graph_b, graph_c]:
            StartNode.objects.create(graph=g, variables={})

        SubGraphNode.objects.create(graph=graph_a, node_name="sub_b", subgraph=graph_b)
        SubGraphNode.objects.create(graph=graph_b, node_name="sub_c", subgraph=graph_c)
        SubGraphNode.objects.create(graph=graph_c, node_name="sub_b", subgraph=graph_b)

        response = auth_client.get(reverse("graphs-export", kwargs={"pk": graph_a.id}))

        assert response.status_code == 404
