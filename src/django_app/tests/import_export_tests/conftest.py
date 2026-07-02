import pytest

from tests.fixtures import *  # noqa: F401,F403

from tables.models import (
    Agent,
    Crew,
    Task,
    TaskContext,
    Graph,
    StartNode,
    CrewNode,
    Edge,
    PythonCode,
    PythonCodeTool,
    RealtimeAgent,
    AgentPythonCodeTools,
    AgentConfiguredTools,
    ToolConfig,
)
from tables.models.realtime_models import RealtimeAgent as RealtimeAgentModel
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
def rich_seeded_db(
    wikipedia_tool,
    llm_config,
    embedding_config,
    openai_realtime_model_config,
    realtime_transcription_config,
):
    """
    Extended seeded_db with LLM configs, embedding configs, realtime configs,
    tasks with context, and graph structure — everything needed for import/export testing.
    """
    # --- Tools ---
    tool1 = ToolConfig.objects.create(name="tool1", tool=wikipedia_tool)

    code = PythonCode.objects.create(
        code="def main(arg1, arg2): return None",
        entrypoint="main",
        libraries="",
    )
    custom_tool = PythonCodeTool.objects.create(
        name="custom_tool1",
        description="description",
        python_code=code,
        variables=[
            {"name": "arg1", "type": "string", "description": "", "default_value": None, "input_type": "agent_input", "required": True},
            {"name": "arg2", "type": "string", "description": "", "default_value": None, "input_type": "agent_input", "required": True},
        ],
    )

    # --- Agents ---
    agent1 = Agent.objects.create(
        role="agent1",
        goal="goal1",
        backstory="backstory1",
        llm_config=llm_config,
    )
    agent2 = Agent.objects.create(
        role="agent2",
        goal="goal2",
        backstory="backstory2",
    )

    agents = [agent1, agent2]

    # Realtime agents (required by AgentStrategy.extract_dependencies_from_instance)
    RealtimeAgent.objects.create(
        agent=agent1,
        realtime_config=openai_realtime_model_config,
        realtime_transcription_config=realtime_transcription_config,
    )
    RealtimeAgent.objects.create(agent=agent2)

    # Tool assignments
    AgentConfiguredTools.objects.create(agent=agent1, toolconfig=tool1)
    AgentPythonCodeTools.objects.create(agent=agent1, pythoncodetool=custom_tool)

    # --- Crew with tasks ---
    crew1 = Crew.objects.create(
        name="crew1",
        embedding_config=embedding_config,
        manager_llm_config=llm_config,
    )
    crew1.agents.set([agent1, agent2])

    task1 = Task.objects.create(
        name="task1",
        crew=crew1,
        agent=agent1,
        instructions="do step 1",
        expected_output="result 1",
        order=1,
    )
    task2 = Task.objects.create(
        name="task2",
        crew=crew1,
        agent=agent2,
        instructions="do step 2",
        expected_output="result 2",
        order=2,
    )
    TaskContext.objects.create(task=task2, context=task1)

    # --- Graph ---
    graph = Graph.objects.create(
        name="graph1",
        metadata={"nodes": [], "edges": []},
    )

    start_node = StartNode.objects.create(graph=graph, variables={})
    crew_node = CrewNode.objects.create(
        crew=crew1,
        graph=graph,
        node_name="crew_node_1",
    )
    Edge.objects.create(
        graph=graph,
        start_node_id=start_node.id,
        end_node_id=crew_node.id,
    )

    return {
        "agents": agents,
        "crews": [crew1],
        "graph": graph,
        "tasks": [task1, task2],
        "llm_config": llm_config,
        "embedding_config": embedding_config,
        "realtime_config": openai_realtime_model_config,
        "realtime_transcription_config": realtime_transcription_config,
        "python_code_tool": custom_tool,
        "python_code": code,
        "tool_config": tool1,
        "start_node": start_node,
        "crew_node": crew_node,
    }
