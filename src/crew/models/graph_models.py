from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def iso_utc_timestamp():
    now = datetime.now(timezone.utc)
    return now.isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass
class GraphMessage:
    session_id: int
    name: str
    execution_order: int
    message_data: dict
    timestamp: str = field(default_factory=iso_utc_timestamp)


@dataclass
class SubGraphStartMessageData:
    state: dict
    input: object
    subgraph_id: int
    subgraph_execution_id: str
    message_type: str = "subgraph_start"
    sse_visible: bool = True


@dataclass
class SubGraphFinishMessageData:
    state: dict
    output: object
    subgraph_execution_id: str
    message_type: str = "subgraph_finish"
    sse_visible: bool = True


@dataclass
class FinishMessageData:
    output: object
    state: dict
    message_type: str = "finish"
    additional_data: dict | None = None
    sse_visible: bool = True


@dataclass
class StartMessageData:
    input: object
    message_type: str = "start"
    sse_visible: bool = True


@dataclass
class ErrorMessageData:
    details: object
    message_type: str = "error"
    sse_visible: bool = True


@dataclass
class PythonMessageData:
    python_code_execution_data: dict
    message_type: str = "python"
    sse_visible: bool = True


@dataclass
class LLMMessageData:
    response: str
    message_type: str = "llm"
    sse_visible: bool = True


@dataclass
class AgentMessageData:
    crew_id: int
    agent_id: int
    thought: str
    tool: str
    tool_input: str
    text: str
    result: str
    message_type: str = "agent"
    sse_visible: bool = True


@dataclass
class AgentFinishMessageData:
    crew_id: int
    agent_id: int
    thought: str
    text: str
    output: str
    message_type: str = "agent_finish"
    sse_visible: bool = True


@dataclass
class UserMessageData:
    crew_id: int
    text: str
    message_type: str = "user"
    sse_visible: bool = True


@dataclass
class TaskMessageData:
    crew_id: int
    task_id: int
    description: str
    raw: str
    name: str
    expected_output: str
    agent: str
    message_type: str = "task"
    sse_visible: bool = True


@dataclass
class UpdateSessionStatusMessageData:
    crew_id: int
    status: str
    status_data: dict = field(default_factory=dict)
    message_type: str = "update_session_status"
    sse_visible: bool = True


@dataclass
class ConditionGroupMessageData:
    group_name: str
    result: bool
    expression: str | None = None
    message_type: str = "condition_group"
    sse_visible: bool = True


@dataclass
class ConditonGroupManipulationMessageData:
    group_name: str
    state: dict
    changed_variables: dict = field(default_factory=dict)
    message_type: str = "condition_group_manipulation"
    sse_visible: bool = True


@dataclass
class NodeExtractedChunksMessageData:
    knowledge_query: str
    collection_id: int
    retrieved_chunks: int
    rag_search_config: dict
    chunks: list[dict]
    token_usage: dict
    input: object
    message_type: str = "extracted_chunks"


@dataclass
class ClassificationPromptMessageData:
    prompt_id: str
    prompt_text: str
    raw_response: str
    parsed_result: Any
    result_variable: str
    usage: dict
    message_type: str = "classification_prompt"
    sse_visible: bool = True
