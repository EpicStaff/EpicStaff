from pydantic import BaseModel
from typing import Literal, Any
from pydantic import ConfigDict
from .ai_providers import LLMData
from .agents import CrewData
from .tools import PythonCodeData


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


class FileExtractorNodeData(BaseModel):
    node_name: str
    input_map: dict[str, Any]
    output_variable_path: str | None = None

    model_config = ConfigDict(from_attributes=True)


class AudioTranscriptionNodeData(BaseModel):
    node_name: str
    input_map: dict[str, Any]
    output_variable_path: str | None = None

    model_config = ConfigDict(from_attributes=True)


class LLMNodeData(BaseModel):
    node_name: str
    llm_data: LLMData
    input_map: dict[str, Any]
    output_variable_path: str | None = None

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
    file_extractor_node_list: list[FileExtractorNodeData] = []
    audio_transcription_node_list: list[AudioTranscriptionNodeData] = []
    subgraph_node_list: list[SubGraphNodeData] = []
    llm_node_list: list[LLMNodeData] = []
    code_agent_node_list: list[CodeAgentNodeData] = []
    edge_list: list[EdgeData] = []
    conditional_edge_list: list[ConditionalEdgeData] = []
    decision_table_node_list: list[DecisionTableNodeData] = []
    classification_decision_table_node_list: list[
        ClassificationDecisionTableNodeData
    ] = []
    entrypoint: str
    end_node: EndNodeData | None
    telegram_trigger_node_data_list: list[TelegramTriggerNodeData] = []

    model_config = ConfigDict(from_attributes=True)


class SubGraphData(BaseModel):
    id: int
    data: GraphData
    initial_state: dict[str, Any] = {}

    model_config = ConfigDict(from_attributes=True)
