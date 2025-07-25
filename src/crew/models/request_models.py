from enum import Enum
from typing import Any, List, Literal, Union
from pydantic import BaseModel, HttpUrl, model_validator


class LLMConfigData(BaseModel):
    model: str
    timeout: float | int | None = None
    temperature: float | None = None
    top_p: float | None = None
    n: int | None = None
    stop: str | list[str] | None = None
    max_completion_tokens: int | None = None
    max_tokens: int | None = None
    presence_penalty: float | None = None
    frequency_penalty: float | None = None
    logit_bias: dict[int, float] | None = None
    response_format: dict[str, Any] | None = None
    seed: int | None = None
    logprobs: bool | None = None
    top_logprobs: int | None = None
    base_url: str | None = None
    api_version: str | None = None
    api_key: str | None = None


class EmbedderConfigData(BaseModel):
    model: str
    deployment_name: str | None = None
    base_url: HttpUrl | None = None
    api_key: str | None = None


class LLMData(BaseModel):
    provider: str
    config: LLMConfigData


class EmbedderData(BaseModel):
    provider: str
    config: EmbedderConfigData


class ToolConfigData(BaseModel):
    id: int
    llm: LLMData | None = None
    embedder: EmbedderData | None = None
    tool_init_configuration: dict[str, Any] | None = None


class ConfiguredToolData(BaseModel):
    name_alias: str
    tool_config: ToolConfigData


class PythonCodeData(BaseModel):
    venv_name: str
    code: str
    entrypoint: str
    libraries: list[str]
    global_kwargs: dict[str, Any] | None = None


class PythonCodeToolData(BaseModel):
    id: int
    name: str
    description: str
    args_schema: dict
    python_code: PythonCodeData


class BaseToolData(BaseModel):
    unique_name: str
    data: PythonCodeToolData | ConfiguredToolData

    @model_validator(mode="before")
    @classmethod
    def validate_data(cls, values: dict):
        unique_name = values.get("unique_name", "")
        data = values.get("data", {})

        try:
            prefix, id = unique_name.split(":")
            assert prefix != ''
            assert id != ''
        except ValueError as e:
            raise ValueError(
                "Invalid unique_name. Unique name should be splited by `:`. \nFor example: python-code-tool:1"
            )
        if prefix == "python-code-tool":
            values["data"] = PythonCodeToolData(**data)
        elif prefix == "configured-tool":
            values["data"] = ConfiguredToolData(**data)
        else:
            raise ValueError(f"Unknown tool prefix: {prefix}")

        return values


class RunToolParamsModel(BaseModel):
    tool_config: ToolConfigData | None = None
    run_args: list[str]
    run_kwargs: dict[str, Any]


class AgentData(BaseModel):
    id: int
    role: str
    goal: str
    backstory: str
    tool_unique_name_list: list[str] = []
    max_iter: int
    max_rpm: int
    max_execution_time: int
    memory: bool
    allow_delegation: bool
    cache: bool
    allow_code_execution: bool
    max_retry_limit: int
    llm: LLMData | None = None
    embedder: EmbedderData | None = None
    function_calling_llm: LLMData | None
    knowledge_collection_id: int | None


class RealtimeAgentData(BaseModel):
    role: str
    goal: str
    backstory: str
    knowledge_collection_id: int | None
    llm: LLMData | None = None
    memory: bool
    tools: list[ConfiguredToolData] = []
    python_code_tools: list[PythonCodeToolData] = []
    connection_key: str


class CrewData(BaseModel):
    class Process(str, Enum):
        sequential = "sequential"
        hierarhical = "hierarchical"

    agents: List[AgentData]
    id: int
    name: str
    process: Process = Process.sequential
    memory: bool = False
    tasks: List["TaskData"] | None
    config: dict[str, Any] | None
    max_rpm: int
    cache: bool
    full_output: bool | None
    planning: bool | None
    embedder: EmbedderData | None
    memory_llm: LLMData | None
    manager_llm: LLMData | None
    planning_llm: LLMData | None
    tools: List[BaseToolData] = []
    knowledge_collection_id: int | None


class TaskData(BaseModel):
    id: int
    name: str
    agent_id: int
    instructions: str
    expected_output: str
    order: int = 1
    human_input: bool
    async_execution: bool
    config: dict | None
    output_model: dict | None
    tool_unique_name_list: list[str] = []
    task_context_id_list: list[int] = []


class SessionData(BaseModel):
    id: int
    graph: "GraphData"
    initial_state: dict[str, Any] = {}


class TaskMessageData(BaseModel):
    crew_id: int
    task_id: int
    description: str
    raw: str
    name: str
    expected_output: str
    agent: str


class ToolInitConfigurationModel(BaseModel):
    tool_init_configuration: dict[str, Any] | None = None


class CodeResultData(BaseModel):
    execution_id: str
    result_data: str | None = None
    stderr: str
    stdout: str
    returncode: int = 0


class CodeTaskData(BaseModel):
    venv_name: str
    libraries: list[str]
    code: str
    execution_id: str
    entrypoint: str
    func_kwargs: dict | None = None
    global_kwargs: dict[str, Any] | None = None


class CrewNodeData(BaseModel):
    node_name: str
    crew: CrewData
    input_map: dict[str, Any]
    output_variable_path: str | None = None


class PythonNodeData(BaseModel):
    node_name: str
    python_code: PythonCodeData
    input_map: dict[str, Any]
    output_variable_path: str | None = None


class LLMNodeData(BaseModel):
    node_name: str
    llm_data: LLMData
    input_map: dict[str, Any]
    output_variable_path: str | None = None


class ConditionData(BaseModel):
    condition: str


class ConditionGroupData(BaseModel):
    group_name: str
    group_type: Literal["simple", "complex"]
    expression: str | None = None
    manipulation: str | None = None
    condition_list: list[ConditionData] = []
    next_node: str | None = None


class DecisionTableNodeData(BaseModel):
    node_name: str
    conditional_group_list: list[ConditionGroupData] = []
    default_next_node: str | None = None
    next_error_node: str | None = None


class EdgeData(BaseModel):
    start_key: str
    end_key: str


class ConditionalEdgeData(BaseModel):
    source: str
    python_code: PythonCodeData
    then: str | None
    input_map: dict[str, Any]


class GraphData(BaseModel):
    name: str
    crew_node_list: list[CrewNodeData] = []
    python_node_list: list[PythonNodeData] = []
    llm_node_list: list[LLMNodeData] = []
    edge_list: list[EdgeData] = []
    conditional_edge_list: list[ConditionalEdgeData] = []
    decision_table_node_list: list[DecisionTableNodeData] = []
    entry_point: str


class GraphSessionMessageData(BaseModel):
    session_id: int
    name: str
    execution_order: int
    timestamp: str
    message_data: dict


class KnowledgeSearchMessage(BaseModel):
    collection_id: int
    uuid: str
    query: str
    search_limit: int | None
    distance_threshold: float | None
