from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from .graph_nodes import GraphData, SubGraphData
from .storage_scope import StorageCredentials


class SessionData(BaseModel):
    id: int
    graph: "GraphData"
    unique_subgraph_list: list[SubGraphData] = []
    initial_state: dict[str, Any] = {}
    output_state: dict[str, Any] = {}
    storage_credentials: StorageCredentials | None = None
    """Temporary storage credentials issued for this session.

    Ephemeral payload — never persisted, never part of graph_schema. Sibling field
    to `graph`, injected by django when publishing session data to crew. The sole
    place where credentials flow from django → crew before distribution to
    storage-demanding nodes.
    """


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    successful_requests: int = 0
    cached_prompt_tokens: int = 0
    total_cost_usd: float = 0.0


class GraphSessionMessageData(BaseModel):
    session_id: int
    name: str
    execution_order: int
    timestamp: str
    message_data: dict
    uuid: str = ""

    model_config = ConfigDict(from_attributes=True)


class StopSessionMessage(BaseModel):
    session_id: int

    model_config = ConfigDict(from_attributes=True)


class WebhookEventData(BaseModel):
    path: str
    payload: dict
    config_id: str | None = None


class ScheduleEventData(BaseModel):
    node_id: int
    graph_id: int
    trigger_type: Literal["schedule"] = "schedule"

    model_config = ConfigDict(from_attributes=True)


class StorageMutation(BaseModel):
    op: str
    path: str


class StorageMutationEvent(BaseModel):
    execution_id: str
    org_prefix: str
    session_id: int | None = None
    mutations: list[StorageMutation]
