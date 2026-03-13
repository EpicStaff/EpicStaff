import pytest
from unittest.mock import Mock
from dotdict import DotDict
from services.graph.graph_session_manager_service import (
    SessionGraphBuilder,
    RedisService,
    CrewParserService,
    RunPythonCodeService,
    KnowledgeSearchService,
)
from src.shared.models import (
    ConditionData,
    ConditionGroupData,
    LLMConfigData,
    LLMData,
    PythonCodeData,
    SessionData,
    GraphData,
    PythonNodeData,
    EdgeData,
    DecisionTableNodeData,
)
import asyncio


@pytest.fixture
def mock_services():
    redis_service = RedisService(
        host="127.0.0.1",
        port="6379",
        password="redis_password",
    )
    return {
        "redis_service": redis_service,
        "crew_parser_service": Mock(spec=CrewParserService),
        "python_code_executor_service": RunPythonCodeService(
            redis_service=redis_service
        ),
        "knowledge_search_service": Mock(spec=KnowledgeSearchService),
    }


@pytest.fixture
def mock_llm_data():
    return LLMData(provider="openai", config=LLMConfigData(model="gpt-4"))


@pytest.fixture
def mock_session_data() -> SessionData:
    return SessionData(
        id=123,
        initial_state={"input": "Hello"},
        graph=GraphData(
            name="example_graph",
            python_node_list=[
                PythonNodeData(
                    node_name="start_node",
                    python_code=PythonCodeData(
                        venv_name="venv-default",
                        code="def main(): return 'next_node'",
                        entrypoint="main",
                        libraries=[],
                        global_kwargs={},
                    ),
                    input_map={},
                    output_variable_path="variables.start_output",
                ),
                PythonNodeData(
                    node_name="end_node",
                    python_code=PythonCodeData(
                        venv_name="venv-default",
                        code="def main(): return 'end'",
                        entrypoint="main",
                        libraries=["requests"],
                        global_kwargs={},
                    ),
                    input_map={},
                    output_variable_path="variables.end_output",
                ),
                PythonNodeData(
                    node_name="error_node",
                    python_code=PythonCodeData(
                        venv_name="venv-default",
                        code="def main(): return 'ERROR HANDELED'",
                        entrypoint="main",
                        libraries=[],
                        global_kwargs={},
                    ),
                    input_map={},
                    output_variable_path="variables.end_output",
                ),
            ],
            edge_list=[
                EdgeData(start_key="__start__", end_key="start_node"),
                EdgeData(start_key="start_node", end_key="decision_table_node_1"),
            ],
            conditional_edge_list=[],
            decision_table_node_list=[
                DecisionTableNodeData(
                    node_name="decision_table_node_1",
                    conditional_group_list=[
                        ConditionGroupData(
                            group_name="check_input",
                            group_type="simple",
                            expression="True",
                            manipulation=None,
                            next_node="end_node",
                            condition_list=[
                                ConditionData(condition="True"),
                                ConditionData(condition="variables.test1 == 2"),
                            ],
                        ),
                        ConditionGroupData(
                            group_name="check_input_no",
                            group_type="complex",
                            expression="variables.test2[0] == 2",
                            manipulation="variables.test1 = 2",
                            next_node="end_node",
                            condition_list=[],
                        ),
                        ConditionGroupData(
                            group_name="error_condion",
                            group_type="simple",
                            expression="True",
                            manipulation=None,
                            next_node=None,
                            condition_list=[
                                ConditionData(condition="variables.test666 == 2"),
                            ],
                        ),
                    ],
                    default_next_node="start_node",
                    next_error_node="error_node",
                )
            ],
            crew_node_list=[],
            entrypoint="start_node",
        ),
    )


def test_compile_from_schema(mock_services, mock_session_data):
    builder = SessionGraphBuilder(
        session_id=mock_session_data.id,
        redis_service=mock_services["redis_service"],
        crew_parser_service=mock_services["crew_parser_service"],
        python_code_executor_service=mock_services["python_code_executor_service"],
        crewai_output_channel="output",
        knowledge_search_service=mock_services["knowledge_search_service"],
    )

    compiled_graph = builder.compile_from_schema(mock_session_data)

    assert compiled_graph is not None
    assert hasattr(compiled_graph, "invoke") or callable(compiled_graph.invoke)


def test_compile_run(mock_services, mock_session_data):
    builder = SessionGraphBuilder(
        session_id=mock_session_data.id,
        redis_service=mock_services["redis_service"],
        crew_parser_service=mock_services["crew_parser_service"],
        python_code_executor_service=mock_services["python_code_executor_service"],
        crewai_output_channel="output",
        knowledge_search_service=mock_services["knowledge_search_service"],
    )

    state = {
        "state_history": [],
        "variables": DotDict({"test1": 1, "test2": [2, {"test3": "secret_value"}]}),
        "system_variables": {},
    }
    compiled_graph = builder.compile_from_schema(mock_session_data)

    async def run_graph():
        asyncio.create_task(mock_services["redis_service"].connect())
        async for stream_mode, chunk in compiled_graph.astream(
            state, stream_mode=["values", "custom"]
        ):
            print(f"Mode: {stream_mode}. Chunk: {chunk}")

    asyncio.run(run_graph())


def test_run_decision_table_node_with_error(mock_services, mock_session_data):
    builder = SessionGraphBuilder(
        session_id=mock_session_data.id,
        redis_service=mock_services["redis_service"],
        crew_parser_service=mock_services["crew_parser_service"],
        python_code_executor_service=mock_services["python_code_executor_service"],
        crewai_output_channel="output",
        knowledge_search_service=mock_services["knowledge_search_service"],
    )

    state = {
        "state_history": [],
        "variables": DotDict({"test1": 4, "test2": [999, {"test3": "secret_value"}]}),
        "system_variables": {},
    }
    compiled_graph = builder.compile_from_schema(mock_session_data)

    async def run_graph():
        asyncio.create_task(mock_services["redis_service"].connect())
        last_chunk = None
        async for stream_mode, chunk in compiled_graph.astream(
            state, stream_mode=["values", "custom"]
        ):
            last_chunk = chunk
            print(f"Mode: {stream_mode}. Chunk: {chunk}")
        assert last_chunk is not None
        assert last_chunk["variables"]["end_output"] == "ERROR HANDELED"

    asyncio.run(run_graph())
