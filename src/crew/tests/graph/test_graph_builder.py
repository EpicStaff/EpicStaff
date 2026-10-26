import pytest
from unittest.mock import AsyncMock, Mock
from fakeredis import FakeAsyncRedis
from dotdict import DotDict
from clients.key_value import KeyValueClient
from services.agent_task_service import AgentTaskService
from services.graph.events import StopEvent
from services.graph.graph_session_manager_service import (
    SessionGraphBuilder,
    RedisService,
    KnowledgeSearchService,
)
from src.shared.models import (
    AgentDefinitionData,
    AgentNodeData,
    AgentNodeTaskData,
    ConditionData,
    ConditionGroupData,
    LLMConfigData,
    LLMData,
    KeyValueNodeData,
    PythonCodeData,
    SessionData,
    GraphData,
    PythonNodeData,
    EdgeData,
    DecisionTableNodeData,
    TaskNodeData,
    SubGraphData,
    SubGraphNodeData,
)
from src.shared.models.storage_scope import StorageCredentials
import asyncio
import json
import uuid


class FakePythonCodeExecutorService:
    """In-process stand-in for RunPythonCodeService.

    Mirrors the sandbox contract (`ExecuteCodeHandler.wrap_code`): kwargs are
    exposed as a DotDict, globals come from `global_kwargs`, the return value is
    JSON-encoded, and any exception becomes returncode 1 with stderr set. Lets
    the graph tests exercise real routing without a live redis + sandbox stack.
    """

    async def run_code(
        self,
        python_code_data: PythonCodeData,
        inputs: dict | None = None,
        additional_global_kwargs: dict | None = None,
        stop_event=None,
        storage_credentials=None,
    ) -> dict:
        namespace: dict = {"DotDict": DotDict}
        namespace.update(python_code_data.global_kwargs or {})
        namespace.update(additional_global_kwargs or {})
        execution_id = str(uuid.uuid4())
        try:
            exec(python_code_data.code, namespace)
            result = namespace[python_code_data.entrypoint](**DotDict(inputs or {}))
            return {
                "execution_id": execution_id,
                "returncode": 0,
                "stderr": "",
                "result_data": json.dumps(result),
            }
        except Exception as e:
            return {
                "execution_id": execution_id,
                "returncode": 1,
                "stderr": str(e),
                "result_data": "null",
            }


@pytest.fixture
def mock_services():
    redis_service = RedisService(
        host="127.0.0.1",
        port=6379,
        user="default",
        password="redis_password",
    )
    # Decision table nodes write their messages straight to Redis; keep unit tests off a live server.
    redis_service.aadd_graph_message = AsyncMock()
    return {
        "redis_service": redis_service,
        "python_code_executor_service": FakePythonCodeExecutorService(),
        "knowledge_search_service": Mock(spec=KnowledgeSearchService),
        "agent_task_service": Mock(spec=AgentTaskService),
        "key_value_client": Mock(spec=KeyValueClient),
    }


@pytest.fixture
def mock_llm_data():
    return LLMData(provider="openai", config=LLMConfigData(model="gpt-4"))


@pytest.fixture
def mock_session_data() -> SessionData:
    return SessionData(
        id=123,
        org_id=1,
        initial_state={"input": "Hello"},
        graph=GraphData(
            name="example_graph",
            python_node_list=[
                PythonNodeData(
                    node_name="start_node",
                    python_code=PythonCodeData(
                        code="def main(): return 'next_node'",
                        entrypoint="main",
                        global_kwargs={},
                    ),
                    input_map={},
                    output_variable_path="variables.start_output",
                ),
                PythonNodeData(
                    node_name="end_node",
                    python_code=PythonCodeData(
                        code="def main(): return 'end'",
                        entrypoint="main",
                        global_kwargs={},
                    ),
                    input_map={},
                    output_variable_path="variables.end_output",
                ),
                PythonNodeData(
                    node_name="error_node",
                    python_code=PythonCodeData(
                        code="def main(): return 'ERROR HANDELED'",
                        entrypoint="main",
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
            entrypoint="start_node",
            end_node=None,
        ),
    )


def _builder(services, session_id=123, **overrides) -> SessionGraphBuilder:
    return SessionGraphBuilder(
        session_id=session_id,
        redis_service=services["redis_service"],
        python_code_executor_service=services["python_code_executor_service"],
        knowledge_search_service=services["knowledge_search_service"],
        stop_event=StopEvent(),
        **overrides,
    )


def _final_variables(compiled_graph, variables: dict) -> dict:
    async def run_graph():
        last_chunk = None
        async for _, chunk in compiled_graph.astream(
            {"state_history": [], "variables": DotDict(variables), "system_variables": {}},
            stream_mode=["values"],
        ):
            last_chunk = chunk
        return last_chunk["variables"]

    return asyncio.run(run_graph())


NEVER_MATCHING_TABLE = DecisionTableNodeData(
    node_name="decision_table_node_1",
    conditional_group_list=[
        ConditionGroupData(
            group_name="never_matches",
            group_type="simple",
            expression="True",
            manipulation=None,
            next_node="error_node",
            condition_list=[ConditionData(condition="variables.test1 == 2")],
        ),
    ],
    default_next_node="end_node",
    next_error_node="error_node",
)


@pytest.mark.parametrize(
    ("variables", "decision_table", "expected_end_output", "expected_message_types"),
    [
        pytest.param(
            {"test1": 1, "test2": [2, {"test3": "secret"}]},
            None,
            "end",
            [
                "start",
                "condition_group",
                "condition_group",
                "condition_group_manipulation",
                "finish",
            ],
            id="matching-row-routes",
        ),
        pytest.param(
            {"test1": 4, "test2": [999, {"test3": "secret"}]},
            None,
            "ERROR HANDELED",
            ["start", "condition_group", "condition_group", "error", "finish"],
            id="failing-condition-routes-to-error-node",
        ),
        pytest.param(
            {"test1": 1},
            NEVER_MATCHING_TABLE,
            "end",
            ["start", "condition_group", "finish"],
            id="no-match-routes-to-default",
        ),
    ],
)
def test_compiled_graph_runs_the_flow_and_routes_through_the_decision_table(
    mock_services,
    mock_session_data,
    variables,
    decision_table,
    expected_end_output,
    expected_message_types,
):
    if decision_table is not None:
        mock_session_data.graph.decision_table_node_list = [decision_table]

    compiled_graph = _builder(mock_services).compile_from_schema(mock_session_data)

    assert _final_variables(compiled_graph, variables)["end_output"] == expected_end_output
    # Subgraph messages bypass the parent stream; the graph message stream is their only way out.
    published_message_types = [
        json.loads(awaited.args[1])["message_data"]["message_type"]
        for awaited in mock_services["redis_service"].aadd_graph_message.await_args_list
    ]
    assert published_message_types == expected_message_types


def _task_node_session_data(mock_llm_data) -> SessionData:
    return SessionData(
        id=456,
        org_id=1,
        initial_state={},
        graph=GraphData(
            name="task_node_graph",
            task_node_list=[
                TaskNodeData(
                    node_name="task_node_1",
                    agent_definition=AgentDefinitionData(
                        id=1,
                        name="researcher",
                        instructions="Research the topic.",
                        llm=mock_llm_data,
                    ),
                    instructions="Summarize the findings.",
                    output_variable_path="variables.result",
                )
            ],
            edge_list=[EdgeData(start_key="__start__", end_key="task_node_1")],
            entrypoint="task_node_1",
            end_node=None,
        ),
    )


def _agent_node_session_data(mock_llm_data) -> SessionData:
    return SessionData(
        id=789,
        org_id=1,
        initial_state={},
        graph=GraphData(
            name="agent_node_graph",
            agent_node_list=[
                AgentNodeData(
                    node_name="agent_node_1",
                    agent_definition=AgentDefinitionData(
                        id=1,
                        name="researcher",
                        instructions="Research the topic.",
                        llm=mock_llm_data,
                    ),
                    tasks=[
                        AgentNodeTaskData(
                            name="task_a", order=0, instructions="Write draft."
                        )
                    ],
                    output_variable_path="variables.result",
                )
            ],
            edge_list=[EdgeData(start_key="__start__", end_key="agent_node_1")],
            entrypoint="agent_node_1",
            end_node=None,
        ),
    )


def _key_value_node_data() -> KeyValueNodeData:
    return KeyValueNodeData(
        node_name="persist_1",
        key_value_table_id=3,
        mode="read",
        entries=[{"key": "k", "value": "variables.out"}],
        input_map={},
        # Saved by older node data; the builder must not hand it to the node.
        output_variable_path="variables.stale",
    )


class FakeStorageAwarePythonCodeExecutorService(FakePythonCodeExecutorService):
    """Fake executor that only serves stored objects when credentials arrive.

    `read_from_storage` is exposed to the executed code exactly like the sandbox
    exposes its storage helpers, and refuses to read without the matching
    credentials — so a node that never receives them cannot read.
    """

    def __init__(self, access_key: str, storage_objects: dict[str, str]):
        self.access_key = access_key
        self.storage_objects = storage_objects
        self.received_storage_credentials: list[StorageCredentials | None] = []

    async def run_code(
        self,
        python_code_data: PythonCodeData,
        inputs: dict | None = None,
        additional_global_kwargs: dict | None = None,
        stop_event=None,
        storage_credentials=None,
    ) -> dict:
        self.received_storage_credentials.append(storage_credentials)

        if python_code_data.use_storage:

            def read_from_storage(path: str) -> str:
                if (
                    storage_credentials is None
                    or storage_credentials.access_key != self.access_key
                ):
                    raise PermissionError("storage credentials missing or invalid")
                return self.storage_objects[path]

            python_code_data = python_code_data.model_copy(
                update={
                    "global_kwargs": {
                        **(python_code_data.global_kwargs or {}),
                        "read_from_storage": read_from_storage,
                    }
                }
            )

        return await super().run_code(
            python_code_data=python_code_data,
            inputs=inputs,
            additional_global_kwargs=additional_global_kwargs,
            stop_event=stop_event,
            storage_credentials=storage_credentials,
        )


def _storage_python_node_data(
    node_name: str, storage_path: str, output_variable_path: str
) -> PythonNodeData:
    return PythonNodeData(
        node_name=node_name,
        python_code=PythonCodeData(
            code=f"def main(): return read_from_storage('{storage_path}')",
            entrypoint="main",
            global_kwargs={},
            use_storage=True,
            storage_allowed_paths=["org_1/"],
            storage_org_prefix="org_1",
            org_id=1,
        ),
        input_map={},
        output_variable_path=output_variable_path,
    )


def _subgraph_node_data(node_name: str, subgraph_id: int, output_variable_path: str):
    return SubGraphNodeData(
        node_name=node_name,
        subgraph_id=subgraph_id,
        input_map={},
        output_variable_path=output_variable_path,
    )


def _storage_subgraph_session_data(
    storage_credentials: StorageCredentials | None,
) -> SessionData:
    inner_graph = GraphData(
        name="inner_storage_graph",
        python_node_list=[
            _storage_python_node_data(
                node_name="storage_node",
                storage_path="org_1/report.txt",
                output_variable_path="variables.storage_output",
            )
        ],
        edge_list=[EdgeData(start_key="__start__", end_key="storage_node")],
        entrypoint="storage_node",
        end_node=None,
    )
    return SessionData(
        id=777,
        org_id=1,
        initial_state={},
        storage_credentials=storage_credentials,
        unique_subgraph_list=[
            SubGraphData(id=1, data=inner_graph, initial_state={}),
        ],
        graph=GraphData(
            name="outer_graph",
            subgraph_node_list=[
                _subgraph_node_data(
                    node_name="sub_node",
                    subgraph_id=1,
                    output_variable_path="variables.sub_output",
                )
            ],
            edge_list=[EdgeData(start_key="__start__", end_key="sub_node")],
            entrypoint="sub_node",
            end_node=None,
        ),
    )


def _two_level_storage_subgraph_session_data(
    storage_credentials: StorageCredentials | None,
) -> SessionData:
    innermost_graph = GraphData(
        name="innermost_storage_graph",
        python_node_list=[
            _storage_python_node_data(
                node_name="storage_node",
                storage_path="org_1/report.txt",
                output_variable_path="variables.storage_output",
            )
        ],
        edge_list=[EdgeData(start_key="__start__", end_key="storage_node")],
        entrypoint="storage_node",
        end_node=None,
    )
    middle_graph = GraphData(
        name="middle_graph",
        subgraph_node_list=[
            _subgraph_node_data(
                node_name="inner_sub_node",
                subgraph_id=2,
                output_variable_path="variables.inner_output",
            )
        ],
        edge_list=[EdgeData(start_key="__start__", end_key="inner_sub_node")],
        entrypoint="inner_sub_node",
        end_node=None,
    )
    return SessionData(
        id=778,
        org_id=1,
        initial_state={},
        storage_credentials=storage_credentials,
        unique_subgraph_list=[
            SubGraphData(id=1, data=middle_graph, initial_state={}),
            SubGraphData(id=2, data=innermost_graph, initial_state={}),
        ],
        graph=GraphData(
            name="outer_graph",
            subgraph_node_list=[
                _subgraph_node_data(
                    node_name="outer_sub_node",
                    subgraph_id=1,
                    output_variable_path="variables.outer_output",
                )
            ],
            edge_list=[EdgeData(start_key="__start__", end_key="outer_sub_node")],
            entrypoint="outer_sub_node",
            end_node=None,
        ),
    )


def _run_compiled_graph(compiled_graph, redis_service):
    async def run_graph():
        last_chunk = None
        async for _stream_mode, chunk in compiled_graph.astream(
            {"state_history": [], "variables": DotDict({}), "system_variables": {}},
            stream_mode=["values"],
        ):
            last_chunk = chunk
        return last_chunk

    return asyncio.run(run_graph())


def test_storage_node_inside_subgraph_receives_session_credentials(mock_services):
    storage_credentials = StorageCredentials(
        access_key="session-access-key", secret_key="session-secret-key"
    )
    executor = FakeStorageAwarePythonCodeExecutorService(
        access_key="session-access-key",
        storage_objects={"org_1/report.txt": "subgraph storage content"},
    )
    builder = SessionGraphBuilder(
        session_id=777,
        redis_service=mock_services["redis_service"],
        python_code_executor_service=executor,
        knowledge_search_service=mock_services["knowledge_search_service"],
        stop_event=StopEvent(),
    )

    compiled_graph = builder.compile_from_schema(
        _storage_subgraph_session_data(storage_credentials)
    )
    last_chunk = _run_compiled_graph(compiled_graph, mock_services["redis_service"])

    assert (
        last_chunk["variables"]["sub_output"]["storage_output"]
        == "subgraph storage content"
    )
    assert executor.received_storage_credentials == [storage_credentials]


def test_storage_node_inside_subgraph_without_session_credentials_gets_none(
    mock_services,
):
    executor = FakeStorageAwarePythonCodeExecutorService(
        access_key="session-access-key",
        storage_objects={"org_1/report.txt": "subgraph storage content"},
    )
    builder = SessionGraphBuilder(
        session_id=777,
        redis_service=mock_services["redis_service"],
        python_code_executor_service=executor,
        knowledge_search_service=mock_services["knowledge_search_service"],
        stop_event=StopEvent(),
    )

    compiled_graph = builder.compile_from_schema(_storage_subgraph_session_data(None))

    with pytest.raises(Exception, match="storage credentials missing or invalid"):
        _run_compiled_graph(compiled_graph, mock_services["redis_service"])

    assert executor.received_storage_credentials == [None]


def test_storage_node_two_levels_deep_receives_session_credentials(mock_services):
    storage_credentials = StorageCredentials(
        access_key="session-access-key", secret_key="session-secret-key"
    )
    executor = FakeStorageAwarePythonCodeExecutorService(
        access_key="session-access-key",
        storage_objects={"org_1/report.txt": "nested storage content"},
    )
    builder = SessionGraphBuilder(
        session_id=778,
        redis_service=mock_services["redis_service"],
        python_code_executor_service=executor,
        knowledge_search_service=mock_services["knowledge_search_service"],
        stop_event=StopEvent(),
    )

    compiled_graph = builder.compile_from_schema(
        _two_level_storage_subgraph_session_data(storage_credentials)
    )
    last_chunk = _run_compiled_graph(compiled_graph, mock_services["redis_service"])

    outer_output = last_chunk["variables"]["outer_output"]
    assert (
        outer_output["inner_output"]["storage_output"] == "nested storage content"
    )
    assert executor.received_storage_credentials == [storage_credentials]


class FakeAgentService:
    async def run_task(self, node_data, stop_event, on_event=None, storage_credentials=None):
        return {"final_text": f"answer to: {node_data.instructions}"}

    async def run_agent_node(self, node_data, stop_event, on_event=None, storage_credentials=None):
        return {"final_text": f"answer to: {node_data.tasks[0].instructions}"}


class FakeKeyValueClient:
    async def read(self, session_id, table_id, keys):
        return {"values": {key: f"stored {key}" for key in keys}, "table_name": "Customers"}


@pytest.mark.parametrize(
    ("session_data", "expected_result"),
    [
        pytest.param(_task_node_session_data, "answer to: Summarize the findings.", id="task-node"),
        pytest.param(_agent_node_session_data, "answer to: Write draft.", id="agent-node"),
    ],
)
def test_agent_backed_nodes_store_the_agents_answer(
    mock_services, mock_llm_data, monkeypatch, session_data, expected_result
):
    # Task nodes read earlier remembered outputs from Redis.
    monkeypatch.setattr(
        mock_services["redis_service"], "aioredis_client", FakeAsyncRedis(decode_responses=True)
    )
    data = session_data(mock_llm_data)
    compiled_graph = _builder(
        mock_services, session_id=data.id, agent_task_service=FakeAgentService()
    ).compile_from_schema(data)

    assert _final_variables(compiled_graph, {})["result"] == expected_result


def test_key_value_node_reads_into_its_entries_not_a_stale_output_path(
    mock_services, mock_session_data
):
    mock_session_data.graph.python_node_list = []
    mock_session_data.graph.decision_table_node_list = []
    mock_session_data.graph.key_value_node_list = [_key_value_node_data()]
    mock_session_data.graph.edge_list = [EdgeData(start_key="__start__", end_key="persist_1")]
    mock_session_data.graph.entrypoint = "persist_1"

    compiled_graph = _builder(mock_services, key_value_client=FakeKeyValueClient()).compile_from_schema(
        mock_session_data
    )

    assert _final_variables(compiled_graph, {}) == {"out": "stored k"}


@pytest.mark.parametrize(
    ("add_nodes", "missing"),
    [
        pytest.param(lambda graph, llm: setattr(graph, "task_node_list", _task_node_session_data(llm).graph.task_node_list), "agent_task_service", id="task-node"),
        pytest.param(lambda graph, llm: setattr(graph, "agent_node_list", _agent_node_session_data(llm).graph.agent_node_list), "agent_task_service", id="agent-node"),
        pytest.param(lambda graph, llm: setattr(graph, "key_value_node_list", [_key_value_node_data()]), "key_value_client", id="key-value-node"),
    ],
)
def test_compile_refuses_a_node_whose_service_was_not_provided(
    mock_services, mock_session_data, mock_llm_data, add_nodes, missing
):
    add_nodes(mock_session_data.graph, mock_llm_data)

    with pytest.raises(RuntimeError, match=missing):
        _builder(mock_services).compile_from_schema(mock_session_data)


def test_compile_passes_knowledge_node_extra_headers(
    mock_services, mock_session_data, monkeypatch
):
    from services.graph import graph_builder
    from src.shared.models import KnowledgeNodeData

    created_nodes = []

    class RecordingKnowledgeNode(graph_builder.KnowledgeNode):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            created_nodes.append(self)

    monkeypatch.setattr(graph_builder, "KnowledgeNode", RecordingKnowledgeNode)
    mock_session_data.graph.knowledge_node_list = [
        KnowledgeNodeData(
            node_name="knowledge_1",
            collection_id=5,
            rag_type_id="naive:2",
            query="q",
            input_map={},
            embedder_extra_headers={"X-Emb": "emb-resolved"},
            llm_extra_headers={"X-Llm": "llm-resolved"},
        )
    ]

    _builder(mock_services, session_id=mock_session_data.id).compile_from_schema(mock_session_data)

    assert len(created_nodes) == 1
    assert created_nodes[0].embedder_extra_headers == {"X-Emb": "emb-resolved"}
    assert created_nodes[0].llm_extra_headers == {"X-Llm": "llm-resolved"}
