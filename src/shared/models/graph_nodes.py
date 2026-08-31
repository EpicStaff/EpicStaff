from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from .agent_service import CollectionSpec, S3FileSpec
from .agents import CrewData
from .ai_providers import LLMData
from .knowledge import RagSearchConfig
from .tools import PythonCodeData
from .surfaces import CombinedSurfaceData
from .tools import BaseToolData


class CrewNodeData(BaseModel):
    node_name: str
    crew: CrewData
    input_map: dict[str, Any]
    output_variable_path: str | None = None
    stream_config: dict[str, Any] = {}

    model_config = ConfigDict(from_attributes=True)


class PythonNodeData(BaseModel):
    node_name: str
    python_code: PythonCodeData
    input_map: dict[str, Any]
    output_variable_path: str | None = None
    stream_config: dict[str, Any] = {}

    model_config = ConfigDict(from_attributes=True)


class KnowledgeNodeData(BaseModel):
    node_name: str
    collection_id: int | None = None
    rag_type_id: str | None = None
    query: str
    rag_search_config: RagSearchConfig | None = None
    input_map: dict[str, Any]
    output_variable_path: str | None = None
    embedder_api_key: str | None = None
    embedder_api_key_secret_id: int | None = Field(default=None, exclude=True)

    model_config = ConfigDict(from_attributes=True)


class FileExtractorNodeData(BaseModel):
    node_name: str
    input_map: dict[str, Any]
    output_variable_path: str | None = None
    storage_allowed_paths: list[str] | None = None
    storage_org_prefix: str | None = None
    session_id: int | None = None
    org_id: int | None = None

    model_config = ConfigDict(from_attributes=True)


class AudioTranscriptionNodeData(BaseModel):
    node_name: str
    input_map: dict[str, Any]
    output_variable_path: str | None = None
    storage_allowed_paths: list[str] | None = None
    storage_org_prefix: str | None = None
    session_id: int | None = None
    org_id: int | None = None

    model_config = ConfigDict(from_attributes=True)


class ConditionData(BaseModel):
    condition: str

    model_config = ConfigDict(from_attributes=True)


class ConditionGroupData(BaseModel):
    group_name: str
    group_type: Literal["simple", "complex"]
    expression: str | None = None
    manipulation: str | None = None
    condition_list: list[ConditionData] = []
    next_node: str | None = None

    model_config = ConfigDict(from_attributes=True)


class DecisionTableNodeData(BaseModel):
    node_name: str
    conditional_group_list: list[ConditionGroupData] = []
    default_next_node: str | None = None
    next_error_node: str | None = None

    model_config = ConfigDict(from_attributes=True)


class PromptConfigData(BaseModel):
    prompt_text: str
    llm_id: int | None = None
    output_schema: dict[str, Any] | str = {}
    result_variable: str = "prompt_result"
    variable_mappings: dict[str, str] = {}
    llm_data: LLMData | None = None


class ClassificationConditionGroupData(BaseModel):
    group_name: str
    expression: str | None = None
    prompt_id: str | None = None
    manipulation: str | None = None
    continue_flag: bool = False
    next_node: str | None = None
    dock_visible: bool = True
    order: int = 0
    field_expressions: dict[str, str] = {}
    field_manipulations: dict[str, str] = {}


class ClassificationDecisionTableNodeData(BaseModel):
    node_name: str
    pre_python_code: PythonCodeData | None = None
    pre_input_map: dict[str, str] = {}
    pre_output_variable_path: str | None = None
    post_python_code: PythonCodeData | None = None
    post_input_map: dict[str, str] = {}
    post_output_variable_path: str | None = None
    condition_groups: list[ClassificationConditionGroupData] = []
    prompts: dict[str, PromptConfigData] = {}
    default_next_node: str | None = None
    next_error_node: str | None = None


class CodeAgentNodeData(BaseModel):
    node_name: str
    llm_config_id: int | None = None
    agent_mode: str = "build"
    session_id: str = ""
    system_prompt: str = ""
    stream_handler_code: str = ""
    libraries: list[str] = []
    polling_interval_ms: int = 1000
    silence_indicator_s: int = 3
    indicator_repeat_s: int = 5
    chunk_timeout_s: int = 30
    inactivity_timeout_s: int = 120
    max_wait_s: int = 300
    input_map: dict[str, Any] = {}
    output_variable_path: str | None = None
    stream_config: dict[str, Any] = {}
    output_schema: dict[str, Any] = {}

    model_config = ConfigDict(from_attributes=True)


class AgentDefinitionData(BaseModel):
    id: int
    name: str
    description: str = ""
    instructions: str = ""
    llm_config_id: int | None = None
    fcm_llm_config_id: int | None = None
    max_iter: int | None = None
    max_rpm: int | None = None
    max_execution_time: int | None = None
    cache: bool | None = None
    max_retry_limit: int | None = None
    default_temperature: float | None = None
    max_tool_calls: int | None = None
    tool_timeout: int | None = None
    max_consecutive_failures: int | None = None
    schema_max_retries: int | None = None
    llm: LLMData | None = None
    fcm_llm: LLMData | None = None

    model_config = ConfigDict(from_attributes=True)


class TaskNodeData(BaseModel):
    node_name: str
    agent_definition: AgentDefinitionData | None = None
    instructions: str = ""
    input_map: dict[str, Any] = {}
    output_variable_path: str | None = None
    output_schema: dict[str, Any] = {}
    remember_output: bool = False
    surface: CombinedSurfaceData = CombinedSurfaceData()
    tools: list[BaseToolData] = []
    collections: list[CollectionSpec] = []
    s3_files: list[S3FileSpec] = []

    model_config = ConfigDict(from_attributes=True)


class AgentNodeTaskData(BaseModel):
    name: str
    order: int
    instructions: str = ""
    output_schema: dict[str, Any] = {}
    context_tasks: list[str] = []

    model_config = ConfigDict(from_attributes=True)


class AgentNodeData(BaseModel):
    node_name: str
    agent_definition: AgentDefinitionData | None = None
    input_map: dict[str, Any] = {}
    output_variable_path: str | None = None
    surface: CombinedSurfaceData = CombinedSurfaceData()
    tools: list[BaseToolData] = []
    collections: list[CollectionSpec] = []
    s3_files: list[S3FileSpec] = []
    tasks: list[AgentNodeTaskData] = []

    model_config = ConfigDict(from_attributes=True)


class EndNodeData(BaseModel):
    node_name: str
    output_map: dict[str, Any]

    model_config = ConfigDict(from_attributes=True)


class EdgeData(BaseModel):
    start_key: str
    end_key: str

    model_config = ConfigDict(from_attributes=True)


class ConditionalEdgeData(BaseModel):
    source: str
    python_code: PythonCodeData
    then: str | None = None
    input_map: dict[str, Any]

    model_config = ConfigDict(from_attributes=True)


class WebhookTriggerNodeData(BaseModel):
    node_name: str
    python_code: PythonCodeData

    model_config = ConfigDict(from_attributes=True)


class TelegramTriggerNodeFieldData(BaseModel):
    parent: Literal["message", "callback_query"]
    field_name: str
    variable_path: str

    model_config = ConfigDict(from_attributes=True)


class TelegramTriggerNodeData(BaseModel):
    node_name: str
    field_list: list[TelegramTriggerNodeFieldData] = []

    model_config = ConfigDict(from_attributes=True)


class ScheduleTriggerNodeData(BaseModel):
    node_name: str
    run_mode: Literal["once", "repeat"] | None = None
    start_date_time: str | None = None
    every: int | None = None
    unit: Literal["seconds", "minutes", "hours", "days", "weeks", "months"] | None = (
        None
    )
    weekdays: list[str] = []
    end_type: Literal["never", "on_date", "after_n_runs"] | None = None
    end_date_time: str | None = None
    max_runs: int | None = None

    model_config = ConfigDict(from_attributes=True)


class SubGraphNodeData(BaseModel):
    node_name: str
    subgraph_id: int
    input_map: dict[str, Any]
    output_variable_path: str | None = None

    model_config = ConfigDict(from_attributes=True)


class GraphData(BaseModel):
    graph_id: int | None = None
    name: str
    crew_node_list: list[CrewNodeData] = []
    webhook_trigger_node_data_list: list[WebhookTriggerNodeData] = []
    python_node_list: list[PythonNodeData] = []
    knowledge_node_list: list[KnowledgeNodeData] = []
    file_extractor_node_list: list[FileExtractorNodeData] = []
    audio_transcription_node_list: list[AudioTranscriptionNodeData] = []
    subgraph_node_list: list[SubGraphNodeData] = []
    code_agent_node_list: list[CodeAgentNodeData] = []
    task_node_list: list[TaskNodeData] = []
    agent_node_list: list[AgentNodeData] = []
    edge_list: list[EdgeData] = []
    conditional_edge_list: list[ConditionalEdgeData] = []
    decision_table_node_list: list[DecisionTableNodeData] = []
    classification_decision_table_node_list: list[
        ClassificationDecisionTableNodeData
    ] = []
    entrypoint: str
    end_node: EndNodeData | None
    telegram_trigger_node_data_list: list[TelegramTriggerNodeData] = []
    schedule_trigger_node_data_list: list[ScheduleTriggerNodeData] = []

    model_config = ConfigDict(from_attributes=True)


class SubGraphData(BaseModel):
    id: int
    data: GraphData
    initial_state: dict[str, Any] = {}

    model_config = ConfigDict(from_attributes=True)


class ScheduleTriggerNodePayload(BaseModel):
    """Flat projection of a schedule trigger node."""

    id: int
    node_name: str
    graph: int = Field(validation_alias=AliasChoices("graph_id", "graph"))
    is_active: bool
    timezone: str = "UTC"
    run_mode: Literal["once", "repeat"] | None = None
    start_date_time: datetime | None = None
    every: int | None = None
    unit: Literal["seconds", "minutes", "hours", "days", "weeks", "months"] | None = (
        None
    )
    weekdays: list[str] | None = None
    end_type: Literal["never", "on_date", "after_n_runs"] | None = None
    end_date_time: datetime | None = None
    max_runs: int | None = None
    current_runs: int = 0

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ScheduleTriggerNodeDeletePayload(BaseModel):
    """Minimal payload for delete events on SCHEDULE_CHANNEL."""

    id: int

    model_config = ConfigDict(from_attributes=True)


class ScheduleTriggerNodeUpdateData(BaseModel):
    """Inner action+node pair carried by ScheduleTriggerNodeUpdateMessage."""

    action: Literal["create", "update", "delete"]
    node: ScheduleTriggerNodePayload | ScheduleTriggerNodeDeletePayload

    model_config = ConfigDict(from_attributes=True)


class ScheduleTriggerNodeUpdateMessage(BaseModel):
    """Envelope published on SCHEDULE_CHANNEL."""

    action: Literal["node_update"] = "node_update"
    data: ScheduleTriggerNodeUpdateData

    model_config = ConfigDict(from_attributes=True)
