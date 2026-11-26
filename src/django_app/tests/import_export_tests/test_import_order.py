import time

import pytest

from tables.import_export.services.import_service import ImportService
from tables.import_export.registry import entity_registry
from tables.import_export.enums import EntityType, NodeType


@pytest.mark.django_db
class TestResolveImportOrder:
    def setup_method(self):
        self.service = ImportService(entity_registry)

    def test_filters_to_present_keys(self):
        data = {
            EntityType.AGENT: [{"id": 1}],
            EntityType.LLM_CONFIG: [{"id": 2}],
        }
        order = self.service._resolve_import_order(data)
        assert set(order) == {EntityType.AGENT, EntityType.LLM_CONFIG}

    def test_preserves_dependency_ordering(self):
        data = {
            EntityType.AGENT: [{"id": 1}],
            EntityType.LLM_CONFIG: [{"id": 2}],
            EntityType.PYTHON_CODE_TOOL: [{"id": 3}],
        }
        order = self.service._resolve_import_order(data)
        assert order.index(EntityType.LLM_CONFIG) < order.index(EntityType.AGENT)
        assert order.index(EntityType.PYTHON_CODE_TOOL) < order.index(EntityType.AGENT)

    def test_empty_data(self):
        order = self.service._resolve_import_order({})
        assert order == []

    def test_ignores_unknown_keys(self):
        data = {
            "UnknownEntity": [{"id": 1}],
            EntityType.AGENT: [{"id": 2}],
        }
        order = self.service._resolve_import_order(data)
        assert order == [EntityType.AGENT]


@pytest.mark.django_db
class TestResolveGraphOrder:
    def setup_method(self):
        self.service = ImportService(entity_registry)

    def test_no_subgraphs(self):
        graphs = [
            {"id": 1, "nodes": []},
            {"id": 2, "nodes": []},
        ]
        result = self.service._resolve_graph_order(graphs)
        assert [g["id"] for g in result] == [1, 2]

    def test_subgraph_dependency(self):
        graphs = [
            {
                "id": 2,
                "nodes": [{"node_type": NodeType.SUBGRAPH_NODE, "subgraph": 1}],
            },
            {"id": 1, "nodes": []},
        ]
        result = self.service._resolve_graph_order(graphs)
        ids = [g["id"] for g in result]
        assert ids.index(1) < ids.index(2)

    def test_circular_dependency_raises(self):
        graphs = [
            {
                "id": 1,
                "nodes": [{"node_type": NodeType.SUBGRAPH_NODE, "subgraph": 2}],
            },
            {
                "id": 2,
                "nodes": [{"node_type": NodeType.SUBGRAPH_NODE, "subgraph": 1}],
            },
        ]
        with pytest.raises(ValueError, match="Circular"):
            self.service._resolve_graph_order(graphs)

    def test_diamond_dependency(self):
        """A depends on B and C, both depend on D."""
        graphs = [
            {
                "id": 1,
                "nodes": [
                    {"node_type": NodeType.SUBGRAPH_NODE, "subgraph": 2},
                    {"node_type": NodeType.SUBGRAPH_NODE, "subgraph": 3},
                ],
            },
            {
                "id": 2,
                "nodes": [{"node_type": NodeType.SUBGRAPH_NODE, "subgraph": 4}],
            },
            {
                "id": 3,
                "nodes": [{"node_type": NodeType.SUBGRAPH_NODE, "subgraph": 4}],
            },
            {"id": 4, "nodes": []},
        ]
        result = self.service._resolve_graph_order(graphs)
        ids = [g["id"] for g in result]
        assert ids.index(4) < ids.index(2)
        assert ids.index(4) < ids.index(3)
        assert ids.index(2) < ids.index(1)
        assert ids.index(3) < ids.index(1)

    def test_external_subgraph_reference_ignored(self):
        """Subgraph ID not in the export payload — should not affect ordering."""
        graphs = [
            {
                "id": 1,
                "nodes": [{"node_type": NodeType.SUBGRAPH_NODE, "subgraph": 999}],
            },
        ]
        result = self.service._resolve_graph_order(graphs)
        assert [g["id"] for g in result] == [1]

    def test_order_is_breadth_first_in_file_order(self):
        """Independent flows keep file order; a flow follows once all it uses are placed.

        Flows 3 and 2 both use flow 1; flow 4 uses nothing. Flows with no dependency go
        first in file order (1, 4), then the flows they unblock, in file order (3, 2).
        """
        graphs = [
            {
                "id": 3,
                "nodes": [{"node_type": NodeType.SUBGRAPH_NODE, "subgraph": 1}],
            },
            {
                "id": 2,
                "nodes": [{"node_type": NodeType.SUBGRAPH_NODE, "subgraph": 1}],
            },
            {"id": 1, "nodes": []},
            {"id": 4, "nodes": []},
        ]
        result = self.service._resolve_graph_order(graphs)
        assert [g["id"] for g in result] == [1, 4, 3, 2]

    def test_cycle_behind_an_acyclic_prefix_raises(self):
        """Flow 1 sorts, but flows 2 and 3 use each other: the whole file is refused."""
        graphs = [
            {"id": 1, "nodes": []},
            {
                "id": 2,
                "nodes": [
                    {"node_type": NodeType.SUBGRAPH_NODE, "subgraph": 1},
                    {"node_type": NodeType.SUBGRAPH_NODE, "subgraph": 3},
                ],
            },
            {
                "id": 3,
                "nodes": [{"node_type": NodeType.SUBGRAPH_NODE, "subgraph": 2}],
            },
        ]
        with pytest.raises(ValueError, match="Circular"):
            self.service._resolve_graph_order(graphs)

    def test_flow_using_the_same_subgraph_twice_waits_for_it_once(self):
        graphs = [
            {
                "id": 2,
                "nodes": [
                    {"node_type": NodeType.SUBGRAPH_NODE, "subgraph": 1},
                    {"node_type": NodeType.SUBGRAPH_NODE, "subgraph": 1},
                ],
            },
            {"id": 1, "nodes": []},
        ]
        result = self.service._resolve_graph_order(graphs)
        assert [g["id"] for g in result] == [1, 2]

    def test_flow_using_itself_raises(self):
        graphs = [
            {"id": 1, "nodes": []},
            {
                "id": 2,
                "nodes": [{"node_type": NodeType.SUBGRAPH_NODE, "subgraph": 2}],
            },
        ]
        with pytest.raises(ValueError, match="Circular"):
            self.service._resolve_graph_order(graphs)

    def test_many_flows_using_one_subgraph_sort_in_linear_time(self):
        """An import file can hold a very large number of flows; ordering them runs
        inside the import transaction, before anything is written, so it must not grow
        with the square of their count. 100,000 flows that all use flow 0 sort in well
        under a second when linear and take over a minute when quadratic."""
        flow_count = 100_000
        graphs = [{"id": 0, "nodes": []}] + [
            {
                "id": flow_id,
                "nodes": [{"node_type": NodeType.SUBGRAPH_NODE, "subgraph": 0}],
            }
            for flow_id in range(1, flow_count)
        ]

        start = time.perf_counter()
        result = self.service._resolve_graph_order(graphs)
        elapsed = time.perf_counter() - start

        assert [g["id"] for g in result] == list(range(flow_count))
        assert elapsed < 5, f"sorting {flow_count} flows took {elapsed:.1f}s"
