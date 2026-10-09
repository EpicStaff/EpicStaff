"""Combining surfaces for a session or a realtime run never reads their authors or last edits."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from agents.models import AgentDefinition, Surface
from agents.models.agent_models import AgentDefaultSurface, SurfacePlace
from agents.services.node_surface_service import NodeSurfaceService
from rbac.authorship import record_last_edit
from tables.models import Graph
from tables.models.graph_models import TaskNode
from tables.services.converter_service import ConverterService
from tables.services.realtime_surface_service import RealtimeSurfaceService
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.fixture
def task_node(acme):
    graph = Graph.objects.create(name="surface-authorship-flow", org=acme)
    return TaskNode.objects.create(graph=graph, node_name="surface-authorship-task")


def _authored_surfaces(org, users, count: int, name_prefix: str) -> list[Surface]:
    surfaces = []
    for index in range(count):
        surface = Surface.objects.create(
            org=org,
            name=f"{name_prefix}-{index}",
            instructions=f"rule {index}",
            created_by=users[index % len(users)],
        )
        record_last_edit(surface, users[(index + 1) % len(users)])
        surfaces.append(surface)
    return surfaces


def _user_reads(captured) -> int:
    return sum('FROM "rbac_user"' in query["sql"] for query in captured.captured_queries)


def _last_edit_reads(captured) -> int:
    return sum(
        'FROM "rbac_resourcelastedit"' in query["sql"] for query in captured.captured_queries
    )


@pytest.mark.django_db
def test_combined_node_surface_reads_no_authorship(task_node, acme, admin_acme, member_only):
    surfaces = _authored_surfaces(acme, [admin_acme, member_only], 3, "node-surface")
    task_node.surface_list.add(*surfaces)

    with CaptureQueriesContext(connection) as captured:
        combined = NodeSurfaceService.build_combined_surface(TaskNode.objects.get(pk=task_node.pk))

    assert _user_reads(captured) == 0
    assert _last_edit_reads(captured) == 0
    assert set(combined["instructions"].split("\n\n")) == {"rule 0", "rule 1", "rule 2"}


@pytest.mark.django_db
def test_realtime_surface_resolution_reads_no_authorship(acme, admin_acme, member_only):
    agent_definition = AgentDefinition.objects.create(
        org=acme,
        name="realtime-authorship-agent",
        instruction_list=[{"name": "Instruction_1.md", "content": "talk"}],
    )
    for surface in _authored_surfaces(acme, [admin_acme, member_only], 2, "realtime-surface"):
        AgentDefaultSurface.objects.create(
            agent_definition=agent_definition, surface=surface, place=SurfacePlace.REALTIME
        )
    resolver = RealtimeSurfaceService(converter_service=ConverterService())

    with CaptureQueriesContext(connection) as captured:
        resolution = resolver.resolve(AgentDefinition.objects.get(pk=agent_definition.pk))

    assert _user_reads(captured) == 0
    assert _last_edit_reads(captured) == 0
    assert resolution.tools == []
