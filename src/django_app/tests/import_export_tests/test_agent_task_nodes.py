"""
Round-trip import/export tests for the AgentNode and TaskNode graph nodes.
"""

import pytest

from tests.fixtures import *  # noqa: F401,F403

from tables.models import (
    Organization,
    Graph,
    AgentNode,
    AgentNodeTask,
    TaskNode,
    McpTool,
    StorageFile,
    SourceCollection,
)
from agents.models import (
    AgentDefinition,
    Surface,
    AgentInlineSurface,
    AgentInlineSurfacePythonTool,
    AgentInlineSurfaceMcpTool,
    AgentInlineSurfaceStorageItem,
    AgentInlineSurfaceKnowledge,
    InlineSurface,
    InlineSurfacePythonTool,
    InlineSurfaceStorageItem,
    InlineSurfaceKnowledge,
    ToolMode,
)
from tables.constants.organization_constants import DEFAULT_ORGANIZATION_NAME
from tables.import_export.enums import EntityType
from tables.import_export.services.export_service import ExportService
from tables.import_export.services.import_service import ImportService
from tables.import_export.registry import entity_registry


@pytest.fixture
def export_service():
    return ExportService(entity_registry)


@pytest.fixture
def import_service():
    return ImportService(entity_registry)


@pytest.fixture
def default_org(db):
    return Organization.objects.get_or_create(name=DEFAULT_ORGANIZATION_NAME)[0]


@pytest.fixture
def mcp_tool():
    return McpTool.objects.create(
        name="mcp_tool_1",
        transport="https://example.com/mcp",
        tool_name="search",
    )


@pytest.fixture
def node_graph_seeded_db(rich_seeded_db, default_org, mcp_tool):
    """
    Builds a Graph holding one AgentNode (with an inline surface, a shared
    surface, and two ordered AgentNodeTasks where the second depends on the
    first) and one TaskNode (with its own inline surface).
    """
    agent_definition = AgentDefinition.objects.create(
        organization=default_org,
        name="agent_def_1",
        description="description",
        instructions="instructions",
        llm_config=rich_seeded_db["llm_config"],
    )

    shared_surface = Surface.objects.create(
        organization=default_org,
        name="shared_surface_1",
    )

    graph = Graph.objects.create(
        name="node_graph_1",
        metadata={"nodes": [], "edges": []},
    )

    agent_node = AgentNode.objects.create(
        graph=graph,
        agent_definition=agent_definition,
    )
    agent_node.surface_list.set([shared_surface])

    agent_inline_surface = AgentInlineSurface.objects.create(
        agent_node=agent_node,
        instructions="x",
    )
    AgentInlineSurfacePythonTool.objects.create(
        agent_inline_surface=agent_inline_surface,
        python_tool=rich_seeded_db["python_code_tool"],
        mode=ToolMode.DENY,
    )
    AgentInlineSurfaceMcpTool.objects.create(
        agent_inline_surface=agent_inline_surface,
        mcp_tool=mcp_tool,
        mode=ToolMode.ALLOW,
    )

    agent_storage_file = StorageFile.objects.create(
        org=default_org,
        path="agent_inline_file.txt",
        name="agent_inline_file.txt",
    )
    AgentInlineSurfaceStorageItem.objects.create(
        agent_inline_surface=agent_inline_surface,
        storage_file=agent_storage_file,
    )
    agent_collection = SourceCollection.objects.create(
        collection_name="agent_inline_collection"
    )
    AgentInlineSurfaceKnowledge.objects.create(
        agent_inline_surface=agent_inline_surface,
        collection=agent_collection,
    )

    task1 = AgentNodeTask.objects.create(
        agent_node=agent_node,
        name="task1",
        order=1,
        instructions="do step 1",
    )
    task2 = AgentNodeTask.objects.create(
        agent_node=agent_node,
        name="task2",
        order=2,
        instructions="do step 2",
    )
    task2.context_tasks.set([task1])

    task_node = TaskNode.objects.create(
        graph=graph,
        agent_definition=agent_definition,
        instructions="t",
    )
    inline_surface = InlineSurface.objects.create(
        task_node=task_node,
        instructions="y",
    )
    InlineSurfacePythonTool.objects.create(
        inline_surface=inline_surface,
        python_tool=rich_seeded_db["python_code_tool"],
        mode=ToolMode.ALLOW,
    )

    task_storage_file = StorageFile.objects.create(
        org=default_org,
        path="task_inline_file.txt",
        name="task_inline_file.txt",
    )
    InlineSurfaceStorageItem.objects.create(
        inline_surface=inline_surface,
        storage_file=task_storage_file,
    )
    task_collection = SourceCollection.objects.create(
        collection_name="task_inline_collection"
    )
    InlineSurfaceKnowledge.objects.create(
        inline_surface=inline_surface,
        collection=task_collection,
    )

    return {
        "graph": graph,
        "agent_definition": agent_definition,
        "shared_surface": shared_surface,
        "agent_node": agent_node,
        "task_node": task_node,
    }


@pytest.mark.django_db
class TestAgentTaskNodeRoundTrip:
    """
    Exporting a Graph pulls in its AgentNode/TaskNode data inline; importing
    recreates both nodes, remaps their agent_definition and surface_list,
    rebuilds the inline surfaces with their tool rows (and modes), rebuilds
    the AgentNodeTask children with their context_tasks dependency, and never
    touches storage or knowledge relations.
    """

    def test_nodes_recreated(
        self, node_graph_seeded_db, export_service, import_service
    ):
        graph = node_graph_seeded_db["graph"]

        export_data = export_service.export_entities(EntityType.GRAPH, [graph.id])
        id_mapper, _ = import_service.import_data(export_data, EntityType.GRAPH)

        new_graph_id = id_mapper.get_new_ids(EntityType.GRAPH)[0]
        new_graph = Graph.objects.get(id=new_graph_id)

        assert new_graph.agent_node_list.count() == 1
        assert new_graph.task_node_list.count() == 1

    def test_agent_definition_remapped(
        self, node_graph_seeded_db, export_service, import_service
    ):
        graph = node_graph_seeded_db["graph"]
        agent_definition = node_graph_seeded_db["agent_definition"]

        export_data = export_service.export_entities(EntityType.GRAPH, [graph.id])
        id_mapper, _ = import_service.import_data(export_data, EntityType.GRAPH)

        new_graph_id = id_mapper.get_new_ids(EntityType.GRAPH)[0]
        new_graph = Graph.objects.get(id=new_graph_id)
        new_agent_node = new_graph.agent_node_list.get()

        assert new_agent_node.agent_definition_id is not None
        assert new_agent_node.agent_definition_id != agent_definition.id
        assert new_agent_node.agent_definition_id in id_mapper.get_new_ids(
            EntityType.AGENT_DEFINITION
        )

    def test_surface_list_remapped(
        self, node_graph_seeded_db, export_service, import_service
    ):
        graph = node_graph_seeded_db["graph"]

        export_data = export_service.export_entities(EntityType.GRAPH, [graph.id])
        id_mapper, _ = import_service.import_data(export_data, EntityType.GRAPH)

        new_graph_id = id_mapper.get_new_ids(EntityType.GRAPH)[0]
        new_graph = Graph.objects.get(id=new_graph_id)
        new_agent_node = new_graph.agent_node_list.get()

        assert new_agent_node.surface_list.count() == 1
        new_surface = new_agent_node.surface_list.get()
        assert new_surface.id in id_mapper.get_new_ids(EntityType.SURFACE)

    def test_inline_surface_tools_and_modes_preserved(
        self, node_graph_seeded_db, export_service, import_service
    ):
        graph = node_graph_seeded_db["graph"]

        export_data = export_service.export_entities(EntityType.GRAPH, [graph.id])
        id_mapper, _ = import_service.import_data(export_data, EntityType.GRAPH)

        new_graph_id = id_mapper.get_new_ids(EntityType.GRAPH)[0]
        new_graph = Graph.objects.get(id=new_graph_id)
        new_agent_node = new_graph.agent_node_list.get()
        new_task_node = new_graph.task_node_list.get()

        new_agent_inline_surface = new_agent_node.inline_surface
        assert new_agent_inline_surface is not None

        new_agent_python_tool = new_agent_inline_surface.python_tools.get()
        assert new_agent_python_tool.mode == ToolMode.DENY

        new_agent_mcp_tool = new_agent_inline_surface.mcp_tools.get()
        assert new_agent_mcp_tool.mode == ToolMode.ALLOW

        new_task_inline_surface = new_task_node.inline_surface
        assert new_task_inline_surface is not None

        new_task_python_tool = new_task_inline_surface.python_tools.get()
        assert new_task_python_tool.mode == ToolMode.ALLOW

    def test_agent_node_tasks_and_context_tasks_recreated(
        self, node_graph_seeded_db, export_service, import_service
    ):
        graph = node_graph_seeded_db["graph"]

        export_data = export_service.export_entities(EntityType.GRAPH, [graph.id])
        id_mapper, _ = import_service.import_data(export_data, EntityType.GRAPH)

        new_graph_id = id_mapper.get_new_ids(EntityType.GRAPH)[0]
        new_graph = Graph.objects.get(id=new_graph_id)
        new_agent_node = new_graph.agent_node_list.get()

        new_tasks = list(new_agent_node.tasks.order_by("order"))
        assert len(new_tasks) == 2

        new_task1, new_task2 = new_tasks
        assert new_task1.name == "task1"
        assert new_task1.order == 1
        assert new_task2.name == "task2"
        assert new_task2.order == 2

        context_task_names = {task.name for task in new_task2.context_tasks.all()}
        assert context_task_names == {"task1"}

    def test_no_storage_or_knowledge_leakage(
        self, node_graph_seeded_db, export_service, import_service
    ):
        """
        The fixture seeds one storage item and one knowledge row on each of
        the AgentInlineSurface and InlineSurface. Import must not recreate
        them for the new nodes — counts must stay exactly at the pre-import
        totals contributed by the original fixture data.
        """
        graph = node_graph_seeded_db["graph"]

        agent_inline_storage_count_before = (
            AgentInlineSurfaceStorageItem.objects.count()
        )
        agent_inline_knowledge_count_before = (
            AgentInlineSurfaceKnowledge.objects.count()
        )
        task_inline_storage_count_before = InlineSurfaceStorageItem.objects.count()
        task_inline_knowledge_count_before = InlineSurfaceKnowledge.objects.count()

        export_data = export_service.export_entities(EntityType.GRAPH, [graph.id])
        import_service.import_data(export_data, EntityType.GRAPH)

        assert (
            AgentInlineSurfaceStorageItem.objects.count()
            == agent_inline_storage_count_before
        )
        assert (
            AgentInlineSurfaceKnowledge.objects.count()
            == agent_inline_knowledge_count_before
        )
        assert (
            InlineSurfaceStorageItem.objects.count() == task_inline_storage_count_before
        )
        assert (
            InlineSurfaceKnowledge.objects.count() == task_inline_knowledge_count_before
        )
