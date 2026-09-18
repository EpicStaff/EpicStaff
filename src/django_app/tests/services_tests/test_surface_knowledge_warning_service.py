"""Tests for SurfaceKnowledgeWarningService.

Covers:
- TaskNode/AgentNode surfaces whose knowledge collection has no search
  config set (naive/graph_basic/graph_local all None) -- the case
  BaseNodePayloadService._build_collection_spec silently drops.
- Inline surfaces are covered too, not just catalog surface_list.
- run_session persists the combined persistent-variable + surface warnings
  into a single SessionWarningMessage row.
"""

from __future__ import annotations

import pytest

from agents.models import Surface
from agents.models.surface_models import (
    AgentInlineSurface,
    AgentInlineSurfaceKnowledge,
    SurfaceKnowledge,
    SurfaceNaiveSearchConfig,
)
from tables.models.graph_models import AgentNode, Graph, TaskNode
from tables.models.knowledge_models.collection_models import SourceCollection
from tables.models.session_models import SessionWarningMessage
from tables.services.session_manager_service import SessionManagerService
from tables.services.surface_knowledge_warning_service import (
    SurfaceKnowledgeWarningService,
)
from tables.services.trigger_spec import TriggerSpec


@pytest.fixture
def graph(default_org):
    return Graph.objects.create(name="surface-knowledge-warning-graph", org=default_org)


@pytest.fixture
def surface(default_org):
    return Surface.objects.create(
        organization=default_org,
        name="surface-knowledge-warning-surface",
        instructions="",
    )


@pytest.fixture
def collection(default_org):
    return SourceCollection.objects.create(
        org=default_org, collection_name="surface-knowledge-warning-collection"
    )


@pytest.fixture
def task_node(graph):
    return TaskNode.objects.create(graph=graph, node_name="warning-task-node")


@pytest.fixture
def agent_node(graph):
    return AgentNode.objects.create(graph=graph, node_name="warning-agent-node")


class _FakeGraphDump:
    def model_dump(self, mode=None):
        return {}


class _FakeSessionData:
    graph = _FakeGraphDump()


def _stub_publish(monkeypatch, session_manager: SessionManagerService | None = None):
    """Stub the run_session tail (SessionData build + Redis publish) so tests
    don't need a fully wired, runnable graph."""
    sm = session_manager or SessionManagerService()
    monkeypatch.setattr(
        sm, "create_session_data", lambda session, token_budget=None: _FakeSessionData()
    )
    monkeypatch.setattr(
        sm.redis_service, "publish_session_data", lambda session_data: 2
    )
    return sm


@pytest.mark.django_db
class TestSurfaceKnowledgeWarningService:
    def test_task_node_surface_without_search_config_warns_once(
        self, graph, task_node, surface, collection
    ):
        SurfaceKnowledge.objects.create(surface=surface, collection=collection)
        task_node.surface_list.set([surface])

        warnings = SurfaceKnowledgeWarningService().build_warnings(graph)

        assert len(warnings) == 1
        warning = warnings[0]
        assert warning["type"] == "knowledge_collection_without_search_config"
        assert warning["node_id"] == task_node.id
        assert warning["node_name"] == "warning-task-node"
        assert warning["node_type"] == "TaskNode"
        assert warning["collection_id"] == collection.collection_id
        assert warning["collection_name"] == collection.collection_name

    def test_task_node_surface_with_naive_search_config_has_no_warning(
        self, graph, task_node, surface, collection
    ):
        knowledge = SurfaceKnowledge.objects.create(
            surface=surface, collection=collection
        )
        SurfaceNaiveSearchConfig.objects.create(surface_knowledge=knowledge)
        task_node.surface_list.set([surface])

        warnings = SurfaceKnowledgeWarningService().build_warnings(graph)

        assert warnings == []

    def test_agent_node_inline_surface_without_search_config_warns(
        self, graph, agent_node, collection
    ):
        inline_surface = AgentInlineSurface.objects.create(agent_node=agent_node)

        AgentInlineSurfaceKnowledge.objects.create(
            agent_inline_surface=inline_surface, collection=collection
        )

        warnings = SurfaceKnowledgeWarningService().build_warnings(graph)

        assert len(warnings) == 1
        warning = warnings[0]
        assert warning["node_id"] == agent_node.id
        assert warning["node_name"] == "warning-agent-node"
        assert warning["node_type"] == "AgentNode"
        assert warning["collection_id"] == collection.collection_id

    def test_graph_with_nodes_but_no_surfaces_has_no_warnings(
        self, graph, task_node, agent_node
    ):
        warnings = SurfaceKnowledgeWarningService().build_warnings(graph)

        assert warnings == []


@pytest.mark.django_db
class TestSessionWarningPersistence:
    def test_run_session_persists_persistent_variable_and_surface_warnings_together(
        self, default_org, graph, task_node, surface, collection, monkeypatch
    ):
        SurfaceKnowledge.objects.create(surface=surface, collection=collection)
        task_node.surface_list.set([surface])

        sm = _stub_publish(monkeypatch)
        monkeypatch.setattr(
            sm.persistent_variables_service,
            "build_run_variables",
            lambda graph, user, payload: type(
                "RunVariablesResult",
                (),
                {
                    "variables": payload or {},
                    "graph_user": None,
                    "warnings": [{"type": "persistent_variable_warning"}],
                },
            )(),
        )

        session_id = sm.run_session(
            graph_id=graph.id,
            variables={},
            user=None,
            trigger=TriggerSpec.manual(),
        )

        warning_row = SessionWarningMessage.objects.get(session_id=session_id)
        warning_types = {w["type"] for w in warning_row.messages}
        assert warning_types == {
            "persistent_variable_warning",
            "knowledge_collection_without_search_config",
        }
