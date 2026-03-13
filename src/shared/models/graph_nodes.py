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

    model_config = ConfigDict(from_attributes=True)


class PythonNodeData(BaseModel):
    node_name: str
    python_code: PythonCodeData
    input_map: dict[str, Any]
    output_variable_path: str | None = None

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


class EndNodeData(BaseModel):
    output_map: dict[str, Any]

    model_config = ConfigDict(from_attributes=True)


class EdgeData(BaseModel):
    start_key: str
    end_key: str

    model_config = ConfigDict(from_attributes=True)


class ConditionalEdgeData(BaseModel):
    source: str
    python_code: PythonCodeData
    then: str | None
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
    name: str
    crew_node_list: list[CrewNodeData] = []
    webhook_trigger_node_data_list: list[WebhookTriggerNodeData] = []
    python_node_list: list[PythonNodeData] = []
    file_extractor_node_list: list[FileExtractorNodeData] = []
    audio_transcription_node_list: list[AudioTranscriptionNodeData] = []
    subgraph_node_list: list[SubGraphNodeData] = []
    llm_node_list: list[LLMNodeData] = []
    edge_list: list[EdgeData] = []
    conditional_edge_list: list[ConditionalEdgeData] = []
    decision_table_node_list: list[DecisionTableNodeData] = []
    entrypoint: str
    end_node: EndNodeData | None
    telegram_trigger_node_data_list: list[TelegramTriggerNodeData] = []

    model_config = ConfigDict(from_attributes=True)


class SubGraphData(BaseModel):
    id: int
    data: GraphData
    initial_state: dict[str, Any] = {}

    model_config = ConfigDict(from_attributes=True)
