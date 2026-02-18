from pathlib import Path
from typing import Generator
from unittest.mock import AsyncMock, MagicMock, patch
import shutil
import pytest
from django.core.management import call_command
from django.core.cache import cache
from tables.validators.python_code_tool_config_validator import (
    PythonCodeToolConfigValidator,
)
from tables.models.python_models import PythonCodeToolConfig, PythonCodeToolConfigField
from tables.models.realtime_models import RealtimeAgent
from tables.models.llm_models import (
    RealtimeConfig,
    RealtimeModel,
    RealtimeTranscriptionConfig,
    RealtimeTranscriptionModel,
)
from tables.models.crew_models import (
    AgentConfiguredTools,
    AgentPythonCodeTools,
    DefaultAgentConfig,
    DefaultCrewConfig,
)
from tables.services.config_service import YamlConfigService
from tables.services.redis_service import RedisService
from tables.services.session_manager_service import SessionManagerService
from tables.services.import_services import (
    RealtimeConfigsImportService,
    RealtimeTranscriptionConfigsImportService,
)

from tables.models import (
    LLMConfig,
    EmbeddingConfig,
    EmbeddingModel,
    LLMModel,
    Provider,
    Crew,
    Agent,
    Task,
    Tool,
    ToolConfig,
    ToolConfigField,
    Session,
    Graph,
    CrewNode,
    Edge,
    StartNode,
    PythonCodeTool,
    PythonCode,
    RealtimeAgent,
)
from tables.serializers.export_serializers import (
    AgentExportSerializer,
    CrewExportSerializer,
    GraphExportSerializer,
)

from tests.helpers import data_to_json_file

import fakeredis


@pytest.fixture(autouse=True)
def reset_db():
    call_command("flush", "--noinput")


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()


@pytest.fixture
def openai_provider() -> Provider:
    openai_provider = Provider(name="openai")
    openai_provider.save()
    return openai_provider


@pytest.fixture
def gpt_4o_llm(openai_provider: Provider) -> LLMModel:
    openai_provider = LLMModel(name="gpt-4o", llm_provider=openai_provider)
    openai_provider.save()
    return openai_provider


@pytest.fixture
def gpt_35_llm(openai_provider: Provider) -> LLMModel:
    openai_provider = LLMModel(name="gpt-3.5-turbo", llm_provider=openai_provider)
    openai_provider.save()
    return openai_provider


@pytest.fixture
def llm_config(gpt_4o_llm) -> LLMConfig:
    llm_config = LLMConfig(
        custom_name="MyGPT-4o",
        model=gpt_4o_llm,
        temperature=0.5,
        is_visible=True,
    )
    llm_config.save()
    return llm_config


@pytest.fixture
def default_agent_config(llm_config) -> DefaultAgentConfig:
    default_agent_config = DefaultAgentConfig(
        allow_delegation=False, memory=False, max_iter=25, llm_config=llm_config
    )
    default_agent_config.save()
    return default_agent_config


@pytest.fixture
def default_crew_config(llm_config) -> DefaultCrewConfig:
    default_crew_config = DefaultCrewConfig(
        process="sequential",
        memory=False,
        embedding_config=None,
        manager_llm_config=llm_config,
    )
    default_crew_config.save()
    return default_crew_config


@pytest.fixture
def new_llm_config(gpt_4o_llm):
    llm_config = LLMConfig(
        model=gpt_4o_llm, temperature=0.9, num_ctx=1024, is_visible=True
    )
    llm_config.save()
    return llm_config


@pytest.fixture
def wikipedia_tool() -> Tool:
    wikipedia = Tool(
        name="Wikipedia",
        name_alias="wikipedia",
        description="Tool to search in wikipedia",
    )
    wikipedia.save()
    return wikipedia


@pytest.fixture
def wikipedia_tool_config(wikipedia_tool) -> ToolConfig:
    return ToolConfig.objects.create(
        name="wikipedia config", tool=wikipedia_tool, configuration={}
    )


@pytest.fixture
def wikipedia_agent(
    gpt_4o_llm: LLMModel, llm_config: LLMConfig, wikipedia_tool_config: ToolConfig
) -> Agent:
    agent = Agent(
        role="Wikipedia searcher",
        goal="Search in wikipedia and give short summary on what you found",
        backstory="You are an experienced wikipedia user",
        allow_delegation=True,
        memory=True,
        max_iter=25,
        llm_config=llm_config,
        fcm_llm_config=llm_config,
    )
    agent.save()

    AgentConfiguredTools.objects.create(
        agent_id=agent.id, toolconfig_id=wikipedia_tool_config.id
    )

    return agent


@pytest.fixture
def embedding_model(openai_provider: Provider) -> EmbeddingModel:
    embedding = EmbeddingModel(
        name="text-embedding-3-small", embedding_provider=openai_provider
    )
    embedding.save()
    return embedding


@pytest.fixture
def embedding_config(embedding_model: EmbeddingModel) -> EmbeddingConfig:
    embedding_config = EmbeddingConfig(
        model=embedding_model,
        task_type="retrieval_document",
    )
    embedding_config.save()
    return embedding_config


@pytest.fixture
def test_task(wikipedia_agent) -> Task:
    task = Task(
        name="test task",
        agent=wikipedia_agent,
        instructions="some instructions",
        expected_output="some output",
        order=1,
    )
    task.save()
    return task


@pytest.fixture
def crew(
    wikipedia_agent: Agent,
    embedding_config: EmbeddingConfig,
    llm_config: LLMConfig,
    test_task: Task,
) -> Crew:
    crew = Crew(
        name="Test Crew",
        description="crew for tests",
        process="sequential",
        memory=True,
        embedding_config=embedding_config,
        manager_llm_config=llm_config,
    )

    crew.save()
    crew.agents.set([wikipedia_agent])
    test_task.crew = crew
    test_task.save()
    crew.save()

    return crew


@pytest.fixture
def graph() -> Graph:
    return Graph.objects.create(name="test")


@pytest.fixture
def session_data(crew: Crew, graph: Graph) -> dict:
    CrewNode.objects.create(node_name="crew_node_1", crew=crew, graph=graph)
    StartNode.objects.create(graph=graph, variables={})
    Edge.objects.create(graph=graph, start_key="__start__", end_key="crew_node_1")
    return {
        "graph_id": graph.pk,
        "variables": {
            "additionalProp1": "string",
            "additionalProp2": "string",
            "additionalProp3": "string",
        },
    }


@pytest.fixture
def session(session_data) -> tuple[Session | dict]:
    session_manager = SessionManagerService()
    return session_manager.create_session(**session_data)


@pytest.fixture
def redis_client_mock() -> Generator[MagicMock, None, None]:
    redis_service = RedisService()
    mock_instance = MagicMock()
    with patch.object(redis_service, "_redis_client", mock_instance):
        yield mock_instance


@pytest.fixture
def fake_redis_client() -> Generator[MagicMock, None, None]:
    redis_mock = MagicMock()
    fake_redis_client = fakeredis.FakeRedis(server=fakeredis.FakeServer())
    with patch("redis.Redis", redis_mock):
        redis_mock.return_value = fake_redis_client
        yield fake_redis_client


@pytest.fixture
def mock_redis_service_async():
    with patch(
        "tables.services.redis_service_async.RedisServiceAsync", autospec=True
    ) as MockService:
        mock = MockService.return_value
        mock.connect = AsyncMock()
        mock.disconnect = AsyncMock()
        mock.async_subscribe = AsyncMock()
        mock.async_unsubscribe = AsyncMock()
        mock.async_publish = AsyncMock()
        mock.listen_to_channel = AsyncMock(return_value=None)
        yield mock


@pytest.fixture
def yaml_config_service_patched_config_path(
    tmp_path: Path,
) -> Generator[MagicMock, None, None]:
    tmp_path.mkdir(exist_ok=True)
    config_path: Path = tmp_path / "config.yaml"
    with patch.object(YamlConfigService, "_CONFIG_PATH", config_path):
        yield config_path

    shutil.rmtree(tmp_path)


@pytest.fixture
def session_factory(db):
    def create_session(**kwargs):
        return Session.objects.create(**kwargs)

    return create_session


@pytest.fixture
def test_tool():
    return Tool.objects.create(
        name="Test Tool",
        name_alias="test_tool",
        description="test tool description",
    )


@pytest.fixture
def test_tool_with_fields(test_tool):
    field1 = ToolConfigField(
        tool=test_tool,
        name="llm_config",
        description="tool llm",
        data_type=ToolConfigField.FieldType.LLM_CONFIG,
        required=True,
    )

    field2 = ToolConfigField(
        tool=test_tool,
        name="embedding_config",
        description="tool embedder",
        data_type=ToolConfigField.FieldType.EMBEDDING_CONFIG,
        required=False,
    )

    field3 = ToolConfigField(
        tool=test_tool,
        name="url",
        description="custom url field",
        data_type=ToolConfigField.FieldType.STRING,
        required=True,
    )

    field1.save()
    field2.save()
    field3.save()

    return test_tool


@pytest.fixture
def test_tool_github_search():
    return Tool.objects.create(
        id=13,
        name="Test GitHub Search Tool",
        name_alias="test_github_search",
        description="test Tool for searching GitHub repositories",
    )


@pytest.fixture
def test_tool_github_search_with_fields(test_tool_github_search):
    llm_config = ToolConfigField(
        tool=test_tool_github_search,
        name="llm_config",
        description="TEST Field for LLM Configuration",
        data_type=ToolConfigField.FieldType.LLM_CONFIG,
        required=True,
    )

    embedding_config = ToolConfigField(
        tool=test_tool_github_search,
        name="embedding_config",
        description="TEST Field for Embedding Configuration",
        data_type=ToolConfigField.FieldType.EMBEDDING_CONFIG,
        required=True,
    )

    github_repo = ToolConfigField(
        tool=test_tool_github_search,
        name="github_repo",
        description="TEST The URL of the GitHub repository",
        data_type=ToolConfigField.FieldType.STRING,
        required=True,
    )

    gh_token = ToolConfigField(
        tool=test_tool_github_search,
        name="gh_token",
        description="TEST Your GitHub Personal Access Token",
        data_type=ToolConfigField.FieldType.STRING,
        required=True,
    )

    content_types = ToolConfigField(
        tool=test_tool_github_search,
        name="content_types",
        description="TEST Specifies the types of content to include in your search.",
        data_type=ToolConfigField.FieldType.ANY,
        required=True,
    )

    llm_config.save()
    embedding_config.save()
    github_repo.save()
    gh_token.save()
    content_types.save()

    return test_tool_github_search


@pytest.fixture
def openai_realtime_model(openai_provider):
    realtime_model = RealtimeModel.objects.create(
        name="Test Realtime Model", provider=openai_provider
    )
    return realtime_model


@pytest.fixture
def openai_realtime_model_config(openai_realtime_model):
    # Create and return the `RealtimeModelConfig` instance
    config = RealtimeConfig.objects.create(
        custom_name="test", api_key="test", realtime_model=openai_realtime_model
    )
    return config


@pytest.fixture
def realtime_transcription_model(openai_provider):
    return RealtimeTranscriptionModel.objects.create(
        name="whisper-1", provider=openai_provider
    )


@pytest.fixture
def realtime_transcription_config(realtime_transcription_model):
    return RealtimeTranscriptionConfig.objects.create(
        custom_name="test_realtime_transcription_config",
        realtime_transcription_model=realtime_transcription_model,
        api_key="mock key",
    )


@pytest.fixture
def wikipedia_agent_with_configured_realtime(
    wikipedia_agent, openai_realtime_model_config, realtime_transcription_config
):
    RealtimeAgent.objects.create(
        agent=wikipedia_agent,
        realtime_config=openai_realtime_model_config,
        realtime_transcription_config=realtime_transcription_config,
    )

    return wikipedia_agent


@pytest.fixture
def seeded_db(wikipedia_tool):
    tool1 = ToolConfig.objects.create(name="tool1", tool=wikipedia_tool)

    code = PythonCode.objects.create(code="def main(arg1, arg2): return None")
    custom_tool = PythonCodeTool.objects.create(
        name="custom_tool1",
        description="description",
        python_code=code,
        args_schema={"arg1": "a", "arg2": "b"},
    )

    agent1 = Agent.objects.create(role="agent1", goal="goal1", backstory="backstory")
    agent2 = Agent.objects.create(role="agent2", goal="goal2", backstory="backstory")
    agent3 = Agent.objects.create(role="agent3", goal="agent3", backstory="backstory")
    agent4 = Agent.objects.create(role="agent4", goal="agent4", backstory="backstory")

    agents = [agent1, agent2, agent3, agent4]
    for agent in agents:
        RealtimeAgent.objects.create(agent=agent)
    AgentConfiguredTools.objects.create(agent=agent1, toolconfig=tool1)
    AgentPythonCodeTools.objects.create(agent=agent2, pythoncodetool=custom_tool)
    AgentConfiguredTools.objects.create(agent=agent3, toolconfig=tool1)
    AgentPythonCodeTools.objects.create(agent=agent3, pythoncodetool=custom_tool)
    AgentPythonCodeTools.objects.create(agent=agent4, pythoncodetool=custom_tool)

    crew1 = Crew.objects.create(name="crew1")
    crew1.agents.set((agent1, agent2))
    crew2 = Crew.objects.create(name="crew2")
    crew2.agents.set((agent1, agent2, agent3, agent4))

    graph = Graph.objects.create(name="graph1")

    CrewNode.objects.create(crew=crew1, graph=graph, node_name="crew_node1")
    CrewNode.objects.create(crew=crew2, graph=graph, node_name="crew_node2")

    return {
        "agents": agents,
        "crews": [crew1, crew2],
        "graph": graph,
    }


@pytest.fixture
def agent_export(seeded_db):
    agent = seeded_db["agents"][0]
    data = AgentExportSerializer(agent).data
    return {"file": data_to_json_file(data=data, filename=agent.role), "agent": agent}


@pytest.fixture
def crew_export(seeded_db):
    crew = seeded_db["crews"][0]
    data = CrewExportSerializer(crew).data
    return {"file": data_to_json_file(data=data, filename=crew.name), "crew": crew}


@pytest.fixture
def graph_export(seeded_db):
    graph = seeded_db["graph"]
    data = GraphExportSerializer(graph).data
    return {"file": data_to_json_file(data=data, filename=graph.name), "graph": graph}


@pytest.fixture
def python_tool_data():
    return {
        "id": 1,
        "python_code": {
            "id": 9,
            "code": "def main(user_id: int): return 'ok'",
            "entrypoint": "main",
            "libraries": "requests",
            "global_kwargs": {"state": {"input": {"user_surname": "TestUser"}}},
        },
        "name": "python tool1",
        "description": "Get user name from id",
        "args_schema": {
            "type": "object",
            "title": "ArgumentsSchema",
            "properties": {"user_id": {"type": "integer", "description": "id of user"}},
        },
    }


@pytest.fixture
def llm_config_data(embedding_model, gpt_4o_llm):
    return {
        "id": 386,
        "model": "gpt-4o",
        "custom_name": "quickstart",
        "temperature": 0.7,
        "top_p": None,
        "stop": None,
        "max_tokens": None,
        "presence_penalty": None,
        "frequency_penalty": None,
        "logit_bias": None,
        "response_format": None,
        "seed": None,
        "logprobs": None,
        "top_logprobs": None,
        "base_url": None,
        "api_version": None,
        "timeout": None,
    }


@pytest.fixture
def realtime_config_data(openai_realtime_model_config):
    return {
        "id": 3,
        "model": "Test Realtime Model",
        "custom_name": "RealtimeTest",
    }


@pytest.fixture
def transcription_config_data(realtime_transcription_config):
    return {
        "id": 1,
        "model": "whisper-1",
        "custom_name": "TranscriptionModel",
    }


@pytest.fixture
def agent():
    return Agent.objects.create(role="tester", goal="goal1")


@pytest.fixture
def agents_map(agent):
    return {123: agent}


@pytest.fixture
def realtime_agent_data():
    return [
        {
            "id": 123,
            "voice": "alloy",
            "realtime_config": 3,
            "realtime_transcription_config": 1,
        }
    ]


@pytest.fixture
def rt_config_service(openai_realtime_model_config):
    data = [
        {
            "id": 3,
            "model": "Test Realtime Model",
            "custom_name": "RealtimeTest",
        }
    ]
    service = RealtimeConfigsImportService(data)
    service.create_configs()
    return service


@pytest.fixture
def rt_transcription_service(realtime_transcription_config):
    data = [{"id": 1, "model": "whisper-1", "custom_name": "TranscriptionModel"}]
    service = RealtimeTranscriptionConfigsImportService(data)
    service.create_configs()
    return service


@pytest.fixture
def agents_data():
    return [
        {
            "id": 679,
            "tools": {"python_tools": [], "configured_tools": []},
            "llm_config": None,
            "fcm_llm_config": None,
            "realtime_agent": 679,
            "entity_type": "Agent",
            "role": "Test",
            "goal": "Test",
            "backstory": "Test",
            "max_iter": 10,
            "max_rpm": 10,
            "max_execution_time": 60,
            "memory": True,
            "allow_delegation": True,
            "cache": True,
            "allow_code_execution": True,
            "max_retry_limit": 3,
            "respect_context_window": True,
            "default_temperature": 0.0,
            "tags": [],
        },
        {
            "id": 694,
            "tools": {"python_tools": [1], "configured_tools": []},
            "llm_config": 386,
            "fcm_llm_config": 386,
            "realtime_agent": 694,
            "entity_type": "Agent",
            "role": "Death Star operator",
            "goal": "Perform Death Star attacks on selected planets",
            "backstory": "Enjoying his work",
            "max_iter": 20,
            "max_rpm": 0,
            "max_execution_time": 0,
            "memory": True,
            "allow_delegation": False,
            "cache": False,
            "allow_code_execution": False,
            "max_retry_limit": 0,
            "respect_context_window": False,
            "default_temperature": 0.0,
            "tags": [],
        },
    ]


@pytest.fixture
def crew_data():
    return [
        {
            "id": 337,
            "agents": [694],
            "tasks": [
                {
                    "id": 413,
                    "tools": {"python_tools": [], "configured_tools": []},
                    "context_tasks": [],
                    "name": "Rate work done",
                    "instructions": "Ask user about ...",
                    "expected_output": "If user satisfied tell ...",
                    "order": 1,
                    "human_input": True,
                    "async_execution": False,
                    "config": None,
                    "output_model": None,
                    "agent": 694,
                }
            ],
            "entity_type": "Project",
            "memory_llm_config": None,
            "manager_llm_config": None,
            "planning_llm_config": None,
            "metadata": {"icon": "ui/star"},
            "description": "Rate user experience about work done",
            "name": "Enjoying work (4)",
            "process": "sequential",
            "memory": False,
            "config": None,
            "max_rpm": 15,
            "cache": True,
            "full_output": True,
            "planning": False,
            "default_temperature": 0.0,
        }
    ]


@pytest.fixture
def python_code() -> PythonCode:
    return PythonCode.objects.create(
        code="def main(): return 42",
        entrypoint="main",
        libraries="requests json",
        global_kwargs={},
    )


@pytest.fixture
def python_code_tool(python_code) -> PythonCodeTool:
    return PythonCodeTool.objects.create(
        name="MyTool",
        description="Test PythonCodeTool",
        args_schema={"type": "object"},
        python_code=python_code,
        favorite=False,
        built_in=False,
    )


@pytest.fixture
def python_code_tool_fields(python_code_tool) -> list[PythonCodeToolConfigField]:
    fields = [
        PythonCodeToolConfigField.objects.create(
            tool=python_code_tool,
            name="arg1",
            description="Argument 1",
            data_type=PythonCodeToolConfigField.FieldType.STRING,
            required=True,
        ),
        PythonCodeToolConfigField.objects.create(
            tool=python_code_tool,
            name="arg2",
            description="Argument 2",
            data_type=PythonCodeToolConfigField.FieldType.INTEGER,
            required=False,
        ),
    ]
    return fields


@pytest.fixture
def python_code_tool_config(python_code_tool) -> PythonCodeToolConfig:
    return PythonCodeToolConfig.objects.create(
        name="config1",
        tool=python_code_tool,
        configuration={"arg1": "value1", "arg2": 10},
    )


@pytest.fixture
def validator():
    return PythonCodeToolConfigValidator()


@pytest.fixture
def mock_tool(mocker):
    """Creates a mock PythonCodeTool."""
    tool = MagicMock(spec=PythonCodeTool)
    return tool


def create_mock_field(name, data_type, required=True):
    """Helper to create a mock configuration field."""
    field = MagicMock(spec=PythonCodeToolConfigField)
    field.name = name
    field.data_type = data_type
    field.required = required
    return field


@pytest.fixture
def tool_config_field_int(db, python_code_tool):
    """Creates an Integer configuration field (required) for the tool."""
    return PythonCodeToolConfigField.objects.create(
        tool=python_code_tool,
        name="batch_size",
        description="Size of the batch",
        data_type=PythonCodeToolConfigField.FieldType.INTEGER,
        required=True,
    )


@pytest.fixture
def tool_config_field_str(db, python_code_tool):
    """Creates a String configuration field (optional) for the tool."""
    return PythonCodeToolConfigField.objects.create(
        tool=python_code_tool,
        name="api_key",
        data_type=PythonCodeToolConfigField.FieldType.STRING,
        required=False,
    )


@pytest.fixture
def existing_config(db, python_code_tool):
    """Creates an existing configuration entry."""
    return PythonCodeToolConfig.objects.create(
        name="production_config",
        tool=python_code_tool,
        configuration={"batch_size": 50},
    )
