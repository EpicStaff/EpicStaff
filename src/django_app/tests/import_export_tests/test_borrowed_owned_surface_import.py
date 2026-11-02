"""
Release 1.3.2 re-imported an agent that owns surfaces as a renamed copy whose
default surfaces, and the surface lists of the nodes running it, still pointed
at the original agent's owned surfaces. Exports of those databases carry that
state; importing them gives the copy agent its own copies instead of failing.
"""

import json

import pytest

from tests.fixtures import *  # noqa: F401,F403

from agents.models import AgentDefaultSurface, AgentDefinition, Surface, SurfacePlace
from agents.validators.surface_validator import SurfaceValidator
from tables.import_export.enums import EntityType
from tables.import_export.registry import entity_registry
from tables.import_export.services.partial_export_service import (
    GraphPartialExportService,
    NodeRef,
)
from tables.import_export.services.partial_import_service import PartialImportService
from tables.models import AgentNode, Graph, StartNode, TaskNode
from tests.helpers import UNRESTRICTED_EXPORT_POLICY


@pytest.fixture
def borrowing_flows(default_org):
    """Agent "Philosopher" owns "thinking" and "banana"; its 1.3.2 re-import copy
    "Philosopher #2" owns nothing but holds both as default surfaces, and its
    AgentNode and TaskNode list "thinking". One flow per agent."""
    owner = AgentDefinition.objects.create(org=default_org, name="Philosopher")
    thinking = Surface.objects.create(
        org=default_org, name="thinking", instructions="think", owner_agent=owner
    )
    banana = Surface.objects.create(
        org=default_org, name="banana", instructions="peel", owner_agent=owner
    )
    borrower = AgentDefinition.objects.create(org=default_org, name="Philosopher #2")
    for agent in (owner, borrower):
        AgentDefaultSurface.objects.create(
            agent_definition=agent, surface=thinking, place=SurfacePlace.FLOW
        )
        AgentDefaultSurface.objects.create(
            agent_definition=agent, surface=banana, place=SurfacePlace.REALTIME
        )

    owner_graph = Graph.objects.create(
        name="owner flow", metadata={"nodes": [], "edges": []}, org=default_org
    )
    StartNode.objects.create(graph=owner_graph, variables={})
    owner_node = AgentNode.objects.create(
        graph=owner_graph, node_name="owner agent node", agent_definition=owner
    )
    owner_node.surface_list.set([thinking])

    borrower_graph = Graph.objects.create(
        name="borrower flow", metadata={"nodes": [], "edges": []}, org=default_org
    )
    StartNode.objects.create(graph=borrower_graph, variables={})
    borrower_agent_node = AgentNode.objects.create(
        graph=borrower_graph, node_name="borrower agent node", agent_definition=borrower
    )
    borrower_agent_node.surface_list.set([thinking])
    borrower_task_node = TaskNode.objects.create(
        graph=borrower_graph, node_name="borrower task node", agent_definition=borrower
    )
    borrower_task_node.surface_list.set([thinking])

    return {
        "owner": owner,
        "borrower": borrower,
        "thinking": thinking,
        "graphs": [owner_graph, borrower_graph],
        "nodes": {
            "owner": owner_node,
            "borrower_agent": borrower_agent_node,
            "borrower_task": borrower_task_node,
        },
    }


@pytest.fixture
def bulk_export_file(borrowing_flows, export_service):
    return json.dumps(
        export_service.export_entities(
            EntityType.GRAPH,
            [graph.id for graph in borrowing_flows["graphs"]],
            policy=UNRESTRICTED_EXPORT_POLICY,
        ).data
    )


def _org_counts(org) -> tuple[int, int]:
    return (
        AgentDefinition.objects.filter(org=org).count(),
        Surface.objects.filter(org=org).count(),
    )


def _assert_agents_api_accepts(agent: AgentDefinition, nodes) -> None:
    SurfaceValidator.validate_agent_default_surfaces(
        [{"surface": row.surface, "place": row.place} for row in agent.default_surfaces.all()],
        agent,
    )
    for node in nodes:
        validate = (
            SurfaceValidator.validate_agent_node_surfaces
            if isinstance(node, AgentNode)
            else SurfaceValidator.validate_task_node_surfaces
        )
        validate(list(node.surface_list.all()), node.agent_definition)


@pytest.mark.django_db
class TestBulkImport:
    def test_borrower_imports_with_its_own_copies(
        self, borrowing_flows, bulk_export_file, import_service
    ):
        borrower = borrowing_flows["borrower"]

        id_mapper, _ = import_service.import_data(json.loads(bulk_export_file), EntityType.GRAPH)

        imported_borrower = AgentDefinition.objects.get(
            id=id_mapper.get(EntityType.AGENT_DEFINITION, borrower.id)
        )
        assert imported_borrower.id != borrower.id
        assert sorted(
            (surface.instructions, surface.owner_agent_id)
            for surface in imported_borrower.owned_surfaces.all()
        ) == [("peel", imported_borrower.id), ("think", imported_borrower.id)]
        assert sorted(
            (row.surface.instructions, row.surface.owner_agent_id, row.place)
            for row in imported_borrower.default_surfaces.select_related("surface")
        ) == [
            ("peel", imported_borrower.id, SurfacePlace.REALTIME),
            ("think", imported_borrower.id, SurfacePlace.FLOW),
        ]
        imported_borrower_graph = Graph.objects.get(
            id=id_mapper.get(EntityType.GRAPH, borrowing_flows["graphs"][1].id)
        )
        borrower_nodes = [
            *imported_borrower_graph.agent_node_list.all(),
            *imported_borrower_graph.task_node_list.all(),
        ]
        assert [
            [surface.owner_agent_id for surface in node.surface_list.all()]
            for node in borrower_nodes
        ] == [[imported_borrower.id], [imported_borrower.id]]
        _assert_agents_api_accepts(imported_borrower, borrower_nodes)

    def test_owner_is_reused_unchanged(self, borrowing_flows, bulk_export_file, import_service):
        owner = borrowing_flows["owner"]
        owned_before = sorted(owner.owned_surfaces.values_list("id", flat=True))

        id_mapper, _ = import_service.import_data(json.loads(bulk_export_file), EntityType.GRAPH)

        assert id_mapper.get(EntityType.AGENT_DEFINITION, owner.id) == owner.id
        assert sorted(owner.owned_surfaces.values_list("id", flat=True)) == owned_before

    def test_reimport_reuses_the_borrowers_copy(
        self, borrowing_flows, bulk_export_file, import_service, default_org
    ):
        borrower_id = borrowing_flows["borrower"].id
        first_id_mapper, _ = import_service.import_data(
            json.loads(bulk_export_file), EntityType.GRAPH
        )
        counts_after_first_import = _org_counts(default_org)

        second_id_mapper, _ = import_service.import_data(
            json.loads(bulk_export_file), EntityType.GRAPH
        )

        assert _org_counts(default_org) == counts_after_first_import
        assert second_id_mapper.get(
            EntityType.AGENT_DEFINITION, borrower_id
        ) == first_id_mapper.get(EntityType.AGENT_DEFINITION, borrower_id)


@pytest.mark.django_db
def test_partial_import_gives_the_borrower_its_own_copy(borrowing_flows, default_org):
    nodes = borrowing_flows["nodes"]
    export_result = GraphPartialExportService(entity_registry).export(
        [
            NodeRef(entity_type=EntityType.AGENT_NODE, node_id=nodes["owner"].id),
            NodeRef(entity_type=EntityType.AGENT_NODE, node_id=nodes["borrower_agent"].id),
            NodeRef(entity_type=EntityType.TASK_NODE, node_id=nodes["borrower_task"].id),
        ],
        org_id=default_org.id,
        policy=UNRESTRICTED_EXPORT_POLICY,
    )
    assert not export_result.has_errors, export_result.errors
    target_graph = Graph.objects.create(
        name="target flow", metadata={"nodes": [], "edges": []}, org=default_org
    )

    result = PartialImportService(entity_registry).import_data(
        json.loads(json.dumps(export_result.data)), target_graph, org_id=default_org.id
    )

    owner_id = result.id_mapper.get(EntityType.AGENT_DEFINITION, borrowing_flows["owner"].id)
    borrower_id = result.id_mapper.get(EntityType.AGENT_DEFINITION, borrowing_flows["borrower"].id)
    content_nodes = [
        *result.content["agent_node_list"],
        *result.content["task_node_list"],
    ]
    surface_owner_by_node_agent = sorted(
        (
            node["agent_definition"],
            [
                Surface.objects.get(id=surface_id).owner_agent_id
                for surface_id in node["surface_list"]
            ],
        )
        for node in content_nodes
    )
    assert surface_owner_by_node_agent == sorted(
        [(owner_id, [owner_id]), (borrower_id, [borrower_id]), (borrower_id, [borrower_id])]
    )
