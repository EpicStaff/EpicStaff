from __future__ import annotations
from typing import TYPE_CHECKING, Generator

from callbacks.session_callback_factory import CrewCallbackFactory
from services.knowledge_search_service import KnowledgeSearchService

if TYPE_CHECKING:
    from models.request_models import AgentData, TaskData, CrewData

import pytest
from polyfactory.factories.pydantic_factory import ModelFactory
from callbacks import GraphSessionCallbackFactory
from unittest.mock import MagicMock
from services.redis_service import RedisService

from models.request_models import (
    AgentData,
    CrewData,
    EmbedderData,
    LLMData,
    TaskData,
)
from services.run_python_code_service import RunPythonCodeService


class CrewDataFactory(ModelFactory[CrewData]):
    __model__ = CrewData


class TaskDataFactory(ModelFactory[TaskData]):
    __model__ = TaskData


class AgentDataFactory(ModelFactory[AgentData]):
    __model__ = AgentData


gpt_4o_data = {
    "provider": "openai",
    "config": {
        "model": "gpt-4o",
        "temperature": 0.7,
    },
}

embedding_model_data = {
    "provider": "openai",
    "config": {
        "model": "text-embedding-3-small",
        "temperature": 0.7,
    },
}

gpt_4o_model_validated = LLMData.model_validate(gpt_4o_data)
embedder_validated_model = EmbedderData.model_validate(embedding_model_data)


@pytest.fixture
def fake_agent_data() -> Generator[AgentData, None, None]:
    fake_agent_data = AgentDataFactory.build()

    fake_agent_data.tool_id_list = []
    fake_agent_data.llm = gpt_4o_model_validated
    fake_agent_data.function_calling_llm = gpt_4o_model_validated
    fake_agent_data.python_code_tool_id_list = []  # Fix test

    yield fake_agent_data


@pytest.fixture
def fake_task_data(fake_agent_data: AgentData) -> Generator[TaskData, None, None]:
    fake_task_data = TaskDataFactory.build()
    fake_task_data.agent_id = fake_agent_data.id
    fake_task_data.task_context_id_list = []
    fake_task_data.output_model = {
        "title": "ArgsSchema",
        "type": "object",
        "properties": {
            "firstName": {"type": "string", "description": "The person's first name."},
            "lastName": {"type": "string", "description": "The person's last name."},
            "age": {
                "description": "Age in years which must be equal to or greater than zero.",
                "type": "integer",
                "minimum": 0,
            },
            "friends": {"type": "array"},
            "comment": {"type": "null"},
        },
    }

    yield fake_task_data


@pytest.fixture
def fake_crew_data(
    fake_agent_data: AgentData, fake_task_data: TaskData
) -> Generator[CrewData, None, None]:
    fake_crew_data = CrewDataFactory.build(process="sequential")
    fake_crew_data.manager_llm = gpt_4o_model_validated
    fake_crew_data.embedder = embedder_validated_model
    fake_crew_data.agents = [fake_agent_data]
    fake_crew_data.tasks = [fake_task_data]
    fake_crew_data.tools = []
    fake_crew_data.python_code_tools = []
    fake_task_data.config = None

    yield fake_crew_data


@pytest.fixture
def mock_redis_service():
    """
    Fixture for mocking the RedisService dependency.
    """
    return MagicMock(spec=RedisService)


@pytest.fixture
def graph_session_callback_factory(mock_redis_service) -> GraphSessionCallbackFactory:
    """
    Fixture for creating a SessionCallbackFactory instance with mocked dependencies.
    """

    graph_session_callback_factory = GraphSessionCallbackFactory(
        session_id=123,
        redis_service=mock_redis_service,
        crewai_output_channel="crewai_output_channel",
    )
    get_done_callback_mock = MagicMock()
    graph_session_callback_factory.get_done_callback = MagicMock(
        return_value=get_done_callback_mock
    )

    return (
        graph_session_callback_factory,
        get_done_callback_mock,
    )


@pytest.fixture
def crew_callback_factory(mock_redis_service, knowledge_search_service) -> CrewCallbackFactory:
    """
    Fixture for creating a SessionCallbackFactory instance with mocked dependencies.
    """

    crew_callback_factory = CrewCallbackFactory(
        session_id=123,
        redis_service=mock_redis_service,
        node_name="crew_node",
        crew_id=456,
        execution_order=0,
        crewai_output_channel="crewai_output_channel",
        stream_writer=None,
        knowledge_search_service=knowledge_search_service
    )

    get_task_callback_mock = MagicMock()
    crew_callback_factory.get_task_callback = MagicMock(
        return_value=get_task_callback_mock
    )

    get_step_callback_mock = MagicMock()
    crew_callback_factory.get_step_callback = MagicMock(
        return_value=get_step_callback_mock
    )

    get_wait_for_user_callback_mock = MagicMock()
    crew_callback_factory.get_wait_for_user_callback = MagicMock(
        return_value=get_wait_for_user_callback_mock
    )

    return (
        crew_callback_factory,
        get_task_callback_mock,
        get_step_callback_mock,
        get_wait_for_user_callback_mock,
    )


@pytest.fixture
def python_code_executor_service(mock_redis_service) -> RunPythonCodeService:
    return RunPythonCodeService(redis_service=mock_redis_service)

@pytest.fixture
def knowledge_search_service(mock_redis_service) -> KnowledgeSearchService:
    return KnowledgeSearchService(redis_service=mock_redis_service)