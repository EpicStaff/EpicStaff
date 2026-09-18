"""
Tests for GraphCopyService copying AgentNode and TaskNode.

Regression coverage for the bug where NODE_COPY_HANDLERS had no entries for
NodeType.AGENT_NODE / NodeType.TASK_NODE, so those nodes (and their edges)
were silently dropped from copied graphs.
"""

import pytest

from agents.models import (
    AgentDefinition,
    AgentInlineSurface,
    AgentInlineSurfaceKnowledge,
    AgentInlineSurfaceMcpTool,
    AgentInlineSurfaceStorageItem,
    InlineSurface,
    InlineSurfaceKnowledge,
    InlineSurfacePythonTool,
    Surface,
    ToolMode,
)
from agents.models.surface_models import (
    AgentInlineSurfaceNaiveSearchConfig,
    InlineSurfaceNaiveSearchConfig,
)
from tables.models import (
    AgentNode,
    AgentNodeTask,
    Edge,
    Graph,
    McpTool,
    SourceCollection,
    StorageFile,
    TaskNode,
)
from tables.models.python_models import PythonCode, PythonCodeTool
from tables.services.copy_services.graph_copy_service import GraphCopyService


@pytest.fixture
def agent_definition(default_org):
    return AgentDefinition.objects.create(
        organization=default_org,
        name="copy-test-agent",
        instructions="do things",
    )


@pytest.fixture
def shared_surface(default_org):
    return Surface.objects.create(organization=default_org, name="copy-test-surface")


@pytest.fixture
def python_tool(default_org):
    code = PythonCode.objects.create(code="def main(): pass")
    return PythonCodeTool.objects.create(
        name="copy-test-py-tool", description="test", python_code=code
    )


@pytest.fixture
def mcp_tool(default_org):
    return McpTool.objects.create(
        org=default_org,
        name="copy-test-mcp-tool",
        transport="https://example.com/mcp",
        tool_name="search",
    )


@pytest.fixture
def storage_file(default_org):
    return StorageFile.objects.create(
        org=default_org, path="copy-test-file.txt", name="copy-test-file.txt"
    )


@pytest.fixture
def source_collection(default_org):
    return SourceCollection.objects.create(
        org=default_org, collection_name="copy-test-collection"
    )


@pytest.fixture
def source_graph(default_org):
    return Graph.objects.create(org=default_org, name="copy-source-graph")


@pytest.mark.django_db
class TestGraphCopyTaskNode:
    def test_task_node_copied_with_fields_surfaces_and_inline_content(
        self,
        source_graph,
        agent_definition,
        shared_surface,
        python_tool,
        storage_file,
        source_collection,
    ):
        task_node = TaskNode.objects.create(
            graph=source_graph,
            agent_definition=agent_definition,
            node_name="task-node-1",
            instructions="do the task",
            output_schema={"type": "object"},
            remember_output=True,
        )
        task_node.surface_list.set([shared_surface])

        inline_surface = InlineSurface.objects.create(
            task_node=task_node, instructions="inline instructions"
        )
        InlineSurfacePythonTool.objects.create(
            inline_surface=inline_surface,
            python_tool=python_tool,
            mode=ToolMode.ALLOW,
        )

        new_graph = GraphCopyService().copy(source_graph, org_id=source_graph.org_id)

        assert new_graph.task_node_list.count() == 1
        new_task_node = new_graph.task_node_list.get()

        assert new_task_node.id != task_node.id
        assert new_task_node.node_name == "task-node-1"
        assert new_task_node.instructions == "do the task"
        assert new_task_node.output_schema == {"type": "object"}
        assert new_task_node.remember_output is True
        assert new_task_node.agent_definition_id == agent_definition.id

        assert list(new_task_node.surface_list.all()) == [shared_surface]

        new_inline_surface = new_task_node.inline_surface
        assert new_inline_surface.id != inline_surface.id
        assert new_inline_surface.instructions == "inline instructions"

        new_python_tool_row = new_inline_surface.python_tools.get()
        assert new_python_tool_row.python_tool_id == python_tool.id
        assert new_python_tool_row.mode == ToolMode.ALLOW

    def test_task_node_inline_surface_storage_and_knowledge_deep_copied(
        self, source_graph, storage_file, source_collection
    ):
        task_node = TaskNode.objects.create(graph=source_graph, node_name="task-node-2")
        inline_surface = InlineSurface.objects.create(task_node=task_node)
        knowledge = InlineSurfaceKnowledge.objects.create(
            inline_surface=inline_surface, collection=source_collection
        )
        InlineSurfaceNaiveSearchConfig.objects.create(
            surface_knowledge=knowledge, search_limit=3
        )

        new_graph = GraphCopyService().copy(source_graph, org_id=source_graph.org_id)
        new_task_node = new_graph.task_node_list.get()
        new_inline_surface = new_task_node.inline_surface

        original_knowledge = inline_surface.knowledge.get()
        new_knowledge = new_inline_surface.knowledge.get()

        assert new_knowledge.id != original_knowledge.id
        assert new_knowledge.collection_id == source_collection.collection_id
        assert new_knowledge.naive_search_config.search_limit == 3

    def test_source_graph_unmodified_after_task_node_copy(
        self, source_graph, python_tool
    ):
        task_node = TaskNode.objects.create(graph=source_graph, node_name="task-node-3")
        inline_surface = InlineSurface.objects.create(task_node=task_node)
        InlineSurfacePythonTool.objects.create(
            inline_surface=inline_surface, python_tool=python_tool, mode=ToolMode.ALLOW
        )

        GraphCopyService().copy(source_graph, org_id=source_graph.org_id)

        assert source_graph.task_node_list.count() == 1
        assert (
            InlineSurfacePythonTool.objects.filter(
                inline_surface=inline_surface
            ).count()
            == 1
        )


@pytest.mark.django_db
class TestGraphCopyAgentNode:
    def test_agent_node_copied_with_tasks_in_order_and_context_remapped(
        self, source_graph, agent_definition, shared_surface
    ):
        agent_node = AgentNode.objects.create(
            graph=source_graph,
            agent_definition=agent_definition,
            node_name="agent-node-1",
        )
        agent_node.surface_list.set([shared_surface])

        task_a = AgentNodeTask.objects.create(
            agent_node=agent_node, name="task-a", order=0, instructions="step a"
        )
        task_b = AgentNodeTask.objects.create(
            agent_node=agent_node, name="task-b", order=1, instructions="step b"
        )
        task_b.context_tasks.set([task_a])

        new_graph = GraphCopyService().copy(source_graph, org_id=source_graph.org_id)

        assert new_graph.agent_node_list.count() == 1
        new_agent_node = new_graph.agent_node_list.get()
        assert new_agent_node.id != agent_node.id
        assert new_agent_node.agent_definition_id == agent_definition.id
        assert list(new_agent_node.surface_list.all()) == [shared_surface]

        new_tasks = list(new_agent_node.tasks.order_by("order"))
        assert [t.name for t in new_tasks] == ["task-a", "task-b"]
        assert [t.instructions for t in new_tasks] == ["step a", "step b"]

        new_task_a, new_task_b = new_tasks
        assert new_task_a.id != task_a.id
        assert new_task_b.id != task_b.id

        new_context_task_ids = list(
            new_task_b.context_tasks.values_list("id", flat=True)
        )
        # context_tasks must point at the NEW sibling, never at the source task
        assert new_context_task_ids == [new_task_a.id]
        assert task_a.id not in new_context_task_ids

    def test_agent_node_inline_surface_deep_copied(
        self, source_graph, mcp_tool, storage_file, source_collection
    ):
        agent_node = AgentNode.objects.create(
            graph=source_graph, node_name="agent-node-2"
        )
        inline_surface = AgentInlineSurface.objects.create(
            agent_node=agent_node, instructions="agent inline instructions"
        )
        AgentInlineSurfaceMcpTool.objects.create(
            agent_inline_surface=inline_surface, mcp_tool=mcp_tool, mode=ToolMode.DENY
        )
        AgentInlineSurfaceStorageItem.objects.create(
            agent_inline_surface=inline_surface, storage_file=storage_file
        )
        knowledge = AgentInlineSurfaceKnowledge.objects.create(
            agent_inline_surface=inline_surface, collection=source_collection
        )
        AgentInlineSurfaceNaiveSearchConfig.objects.create(
            surface_knowledge=knowledge, search_limit=7
        )

        new_graph = GraphCopyService().copy(source_graph, org_id=source_graph.org_id)
        new_agent_node = new_graph.agent_node_list.get()
        new_inline_surface = new_agent_node.inline_surface

        assert new_inline_surface.id != inline_surface.id
        assert new_inline_surface.instructions == "agent inline instructions"

        new_mcp_row = new_inline_surface.mcp_tools.get()
        assert new_mcp_row.mcp_tool_id == mcp_tool.id
        assert new_mcp_row.mode == ToolMode.DENY

        new_storage_row = new_inline_surface.storage_items.get()
        assert new_storage_row.storage_file_id == storage_file.id

        new_knowledge_row = new_inline_surface.knowledge.get()
        assert new_knowledge_row.collection_id == source_collection.collection_id
        assert new_knowledge_row.naive_search_config.search_limit == 7

    def test_edges_touching_agent_and_task_nodes_are_remapped(self, source_graph):
        agent_node = AgentNode.objects.create(
            graph=source_graph, node_name="agent-node-3"
        )
        task_node = TaskNode.objects.create(graph=source_graph, node_name="task-node-4")
        Edge.objects.create(
            graph=source_graph, start_node_id=agent_node.id, end_node_id=task_node.id
        )

        new_graph = GraphCopyService().copy(source_graph, org_id=source_graph.org_id)

        new_agent_node = new_graph.agent_node_list.get()
        new_task_node = new_graph.task_node_list.get()
        new_edge = new_graph.edge_list.get()

        assert new_edge.start_node_id == new_agent_node.id
        assert new_edge.end_node_id == new_task_node.id

    def test_source_graph_unmodified_after_agent_node_copy(self, source_graph):
        agent_node = AgentNode.objects.create(
            graph=source_graph, node_name="agent-node-4"
        )
        task_a = AgentNodeTask.objects.create(
            agent_node=agent_node, name="task-a", order=0
        )
        AgentNodeTask.objects.create(
            agent_node=agent_node, name="task-b", order=1
        ).context_tasks.set([task_a])

        GraphCopyService().copy(source_graph, org_id=source_graph.org_id)

        assert source_graph.agent_node_list.count() == 1
        assert AgentNodeTask.objects.filter(agent_node=agent_node).count() == 2
