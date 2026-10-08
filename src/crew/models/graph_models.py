import json
import uuid
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import UTC, datetime
from typing import Any


def iso_utc_timestamp():
    now = datetime.now(UTC)
    return now.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def dataclass_to_shallow_dict(instance) -> dict:
    """Top-level fields as a dict; values are shared, not deep-copied like `asdict`."""
    return {
        dataclass_field.name: getattr(instance, dataclass_field.name)
        for dataclass_field in fields(instance)
    }


def encode_dataclass_as_dict(value: object) -> dict:
    """`json.dumps` default hook: dataclasses become dicts, anything else raises."""
    if is_dataclass(value) and not isinstance(value, type):
        return dataclass_to_shallow_dict(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


@dataclass
class GraphMessage:
    session_id: int
    name: str
    execution_order: int
    message_data: dict
    timestamp: str = field(default_factory=iso_utc_timestamp)
    node_type: str = ""

    def to_payload(self) -> dict:
        """Shallow dict for the graph message stream with a fresh `uuid`; `message_data` is a dict.

        The `uuid` is the event identity: Django deduplicates on it and the audit trail reuses it.
        """
        payload = dataclass_to_shallow_dict(self)
        if is_dataclass(self.message_data):
            payload["message_data"] = dataclass_to_shallow_dict(self.message_data)
        payload["uuid"] = str(uuid.uuid4())
        return payload

    @staticmethod
    def encode_payload(payload: dict) -> str:
        """JSON of a `to_payload()` dict, encoded once for the stream and the audit trail.

        The payload shares values with live flow state; the encoded string is the snapshot.
        """
        return json.dumps(payload, default=encode_dataclass_as_dict)


@dataclass
class SubGraphStartMessageData:
    state: dict
    input: object
    subgraph_id: int
    subgraph_execution_id: str
    message_type: str = "subgraph_start"


@dataclass
class SubGraphFinishMessageData:
    state: dict
    output: object
    subgraph_execution_id: str
    message_type: str = "subgraph_finish"


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
    group_name: str
    result: bool
    expression: str | None = None
    message_type: str = "condition_group"


@dataclass
class ConditonGroupManipulationMessageData:
    group_name: str
    state: dict
    changed_variables: dict = field(default_factory=dict)
    message_type: str = "condition_group_manipulation"


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


@dataclass
class KeyValueMessageEntry:
    key: str
    # read: target path; write: source path (raw, incl. |default); delete: None
    path: str | None = None
    # read: key in values (a stored null counts as found); delete: key existed and was
    # deleted; write: None
    found: bool | None = None
    # write only
    created: bool | None = None
    # read: stored value; write: value written; delete: deleted value. None when not found.
    value: Any = None
    # True when the value did not fit the message budget; `value` is then a JSON-text preview
    truncated: bool = False


@dataclass
class KeyValueMessageData:
    mode: str  # "read" | "write" | "delete"
    table_id: int
    table_name: str
    entries: list[KeyValueMessageEntry]
    deleted_count: int | None = None  # delete only
    message_type: str = "key_value"
