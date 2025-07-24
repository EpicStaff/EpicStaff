from typing import Any, TypedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone


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
class FinishMessageData:
    output: object
    state: dict
    message_type: str = "finish"
    additional_data: dict | None = None


@dataclass
class StartMessageData:
    input: object
    message_type: str = "start"


@dataclass
class ErrorMessageData:
    details: object
    message_type: str = "error"


@dataclass
class PythonMessageData:
    python_code_execution_data: dict
    message_type: str = "python"


@dataclass
class LLMMessageData:
    response: str
    message_type: str = "llm"


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


@dataclass
class AgentFinishMessageData:
    crew_id: int
    agent_id: int
    thought: str
    text: str
    output: str
    message_type: str = "agent_finish"


@dataclass
class UserMessageData:
    crew_id: int
    text: str
    message_type: str = "user"


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


@dataclass
class UpdateSessionStatusMessageData:
    crew_id: int
    status: str
    status_data: dict = field(default_factory=dict)
    message_type: str = "update_session_status"


@dataclass
class ConditionGroupMessageData:
    group_name: int
    result: bool


@dataclass
class ConditonGroupManipulationMessageData:
    group_name: int
    state: dict
