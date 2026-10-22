import copy

import pytest
from django.urls import reverse

from tables.graph_versioning.services import GraphVersioningService
from tables.import_export.enums import EntityType, NodeType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.registry import entity_registry
from tables.import_export.services.export_service import ExportService
from tables.import_export.services.partial_export_service import (
    GraphPartialExportService,
    NodeRef,
)
from tables.import_export.services.partial_import_service import PartialImportService
from tables.models import AgentNode, Crew, CrewNode, Graph, PythonCode, PythonNode, StartNode
from tables.services.node_number_service import NodeNumberService
from tests.helpers import data_to_json_file
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


def _flow(org, name="Numbered Flow"):
    graph = Graph.objects.create(name=name, org=org, metadata={"nodes": [], "edges": []})
    StartNode.objects.create(graph=graph, variables={})
    return graph


def _python_node(graph, node_name, node_number):
    code = PythonCode.objects.create(code="def main(): ...", entrypoint="main", libraries="")
    return PythonNode.objects.create(
        graph=graph, node_name=node_name, python_code=code, node_number=node_number
    )


def _agent_node(graph, node_name, node_number):
    return AgentNode.objects.create(graph=graph, node_name=node_name, node_number=node_number)


def _numbers_by_name(graph):
    graph.refresh_from_db()
    return {
        **dict(graph.agent_node_list.values_list("node_name", "node_number")),
        **dict(graph.python_node_list.values_list("node_name", "node_number")),
    }


def _export(graph):
    return ExportService(entity_registry).export_entities(EntityType.GRAPH, [graph.id])


def _import(client, org, export_data, **settings):
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client.post(
        reverse("graphs-import-entity"),
        {"file": data_to_json_file(data=export_data, filename="flow.json"), **settings},
        format="multipart",
    )


def _as_v3_file(export_data):
    """The file the previous format would have written: badge in the name and metadata."""
    legacy = copy.deepcopy(export_data)
    legacy["version"] = 3
    for graph in legacy[EntityType.GRAPH]:
        for node in graph["nodes"]:
            number = node.pop("node_number", None)
            if number is None:
                continue
            node["node_name"] = f"{node['node_name']} #{number}"
            node["metadata"] = {**(node.get("metadata") or {}), "nodeNumber": number}
    return legacy


def _partial_export(nodes):
    refs = [
        NodeRef(
            entity_type=(
                EntityType.PYTHON_NODE if isinstance(node, PythonNode) else EntityType.AGENT_NODE
            ),
            node_id=node.id,
        )
        for node in nodes
    ]
    result = GraphPartialExportService(entity_registry).export(refs, org_id=nodes[0].graph.org_id)
    assert not result.has_errors, result.errors
    return result.data


def _partial_import(export_data, graph):
    PartialImportService(entity_registry).import_data(
        export_data=export_data, graph=graph, org_id=graph.org_id
    )


@pytest.fixture
def source_flow(acme):
    """A flow numbered #1, #4, #5 whose export lists #5 first: python nodes export before agents."""
    graph = _flow(acme, "Source")
    _agent_node(graph, "Agent", 1)
    _agent_node(graph, "Second agent", 4)
    _python_node(graph, "Python", 5)
    return graph


def _imported_flow(acme, source):
    return Graph.objects.filter(org=acme).exclude(pk=source.pk).get()


@pytest.mark.django_db
class TestNodeNumberIsExported:
    def test_full_export_carries_each_node_number(self, source_flow):
        nodes = _export(source_flow)[EntityType.GRAPH][0]["nodes"]

        numbers = {node["node_name"]: node["node_number"] for node in nodes if "node_name" in node}
        assert numbers == {"Agent": 1, "Second agent": 4, "Python": 5}

    def test_partial_export_carries_each_node_number(self, source_flow):
        python_node = source_flow.python_node_list.get()
        agent_node = source_flow.agent_node_list.get(node_name="Second agent")

        data = _partial_export([python_node, agent_node])

        assert [node["node_number"] for node in data[EntityType.PYTHON_NODE]] == [5]
        assert [node["node_number"] for node in data[EntityType.AGENT_NODE]] == [4]

    def test_version_snapshot_carries_each_node_number(self, source_flow):
        version = GraphVersioningService().save_version(graph=source_flow, name="v1")

        numbers = {
            node["node_name"]: node["node_number"]
            for node in version.snapshot["nodes"]
            if "node_name" in node
        }
        assert numbers == {"Agent": 1, "Second agent": 4, "Python": 5}

    def test_export_and_snapshot_leave_out_the_graph_counter(self, source_flow):
        version = GraphVersioningService().save_version(graph=source_flow, name="v1")

        assert "node_number_seq" not in _export(source_flow)[EntityType.GRAPH][0]
        assert "node_number_seq" not in version.snapshot


@pytest.mark.django_db
class TestFullImportRenumbersInSourceOrder:
    def test_new_flow_is_numbered_one_to_k_in_source_order(
        self, client_as, admin_acme, acme, source_flow
    ):
        response = _import(client_as(admin_acme), acme, _export(source_flow))

        assert response.status_code == 200, response.content
        imported = _imported_flow(acme, source_flow)
        assert _numbers_by_name(imported) == {"Agent": 1, "Second agent": 2, "Python": 3}
        assert imported.node_number_seq == 3

    def test_v3_file_is_converted_to_clean_names_and_the_same_order(
        self, client_as, admin_acme, acme, source_flow
    ):
        response = _import(client_as(admin_acme), acme, _as_v3_file(_export(source_flow)))

        assert response.status_code == 200, response.content
        imported = _imported_flow(acme, source_flow)
        assert _numbers_by_name(imported) == {"Agent": 1, "Second agent": 2, "Python": 3}
        assert imported.node_number_seq == 3
        agent_metadata = imported.agent_node_list.values_list("metadata", flat=True)
        assert all("nodeNumber" not in (metadata or {}) for metadata in agent_metadata)

    def test_replace_existing_numbers_from_one(self, client_as, admin_acme, acme):
        holder = _flow(acme, "Holder")
        _agent_node(holder, "Late", 7)
        _python_node(holder, "Early", 3)
        NodeNumberService().raise_to(holder.id, 8)
        export_data = _export(holder)

        response = _import(
            client_as(admin_acme), acme, export_data, preserve_uuids=True, replace_existing=True
        )

        assert response.status_code == 200, response.content
        assert Graph.objects.filter(org=acme).count() == 1
        assert _numbers_by_name(holder) == {"Early": 1, "Late": 2}
        assert holder.node_number_seq == 2

    def test_replace_existing_numbers_above_a_legacy_crew_node_the_wipe_keeps(
        self, client_as, admin_acme, acme
    ):
        holder = _flow(acme, "Holder")
        crew_node = CrewNode.objects.create(
            graph=holder,
            node_name="legacy crew",
            crew=Crew.objects.create(org=acme, name="legacy"),
            node_number=4,
        )
        _python_node(holder, "Python", 1)
        _agent_node(holder, "Agent", 2)
        export_data = _export(holder)

        response = _import(
            client_as(admin_acme), acme, export_data, preserve_uuids=True, replace_existing=True
        )

        assert response.status_code == 200, response.content
        assert _numbers_by_name(holder) == {"Python": 5, "Agent": 6}
        assert holder.node_number_seq == 6
        assert CrewNode.objects.get(pk=crew_node.pk).node_number == 4


@pytest.mark.django_db
class TestPartialImportNumbersAboveTheTargetsCounter:
    def test_pasted_nodes_count_up_from_the_counter_in_source_order(self, acme):
        source = _flow(acme, "Source")
        python_node = _python_node(source, "Python", 5)
        agent_node = _agent_node(source, "Agent", 2)
        target = _flow(acme, "Target")
        NodeNumberService().raise_to(target.id, 10)

        _partial_import(_partial_export([python_node, agent_node]), target)

        assert _numbers_by_name(target) == {"Agent": 11, "Python": 12}
        assert target.node_number_seq == 12

    def test_legacy_file_without_node_number_has_its_badge_names_cleaned(self, acme):
        source = _flow(acme, "Source")
        python_node = _python_node(source, "Python", 5)
        agent_node = _agent_node(source, "Agent", 2)
        legacy = _partial_export([python_node, agent_node])
        for entity_type in (EntityType.PYTHON_NODE, EntityType.AGENT_NODE):
            for node in legacy[entity_type]:
                number = node.pop("node_number")
                node["node_name"] = f"{node['node_name']} #{number}"
                node["metadata"] = {**(node.get("metadata") or {}), "nodeNumber": number}
        target = _flow(acme, "Target")

        _partial_import(legacy, target)

        assert _numbers_by_name(target) == {"Agent": 1, "Python": 2}
        python_metadata = target.python_node_list.values_list("metadata", flat=True).get()
        assert "nodeNumber" not in (python_metadata or {})


@pytest.mark.django_db
class TestCrewNodeImportIsSkipped:
    """CrewNode has no import_export strategy anymore (CrewAI execution removed),
    but NodeType.CREW_NODE stays a recognized enum member so old exports still
    parse. `_create_nodes` must skip crew-node entries with a warning instead
    of raising or reviving CrewAI-era nodes."""

    def test_crew_node_payload_is_skipped_and_takes_no_number(self, graph, default_org):
        crew = Crew.objects.create(name="legacy crew", org=default_org)
        id_mapper = IDMapper()
        id_mapper.map(EntityType.CREW, crew.id, crew.id, was_created=False)
        nodes_data = [
            {
                "id": 9999,
                "node_type": NodeType.CREW_NODE,
                "crew": crew.id,
                "node_name": "Crew",
                "node_number": 99,
                "metadata": {},
            }
        ]

        entity_registry.get_strategy(EntityType.GRAPH)._create_nodes(
            nodes_data, graph, IDMapper(), id_mapper
        )

        graph.refresh_from_db()
        assert not CrewNode.objects.filter(graph=graph).exists()
        assert graph.node_number_seq == 0
