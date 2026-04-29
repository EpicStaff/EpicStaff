from pydantic import BaseModel
from typing import Any
from pydantic import ConfigDict
from .graph_nodes import GraphData, SubGraphData


class SessionData(BaseModel):
    id: int
    graph: "GraphData"
    unique_subgraph_list: list[SubGraphData] = []
    initial_state: dict[str, Any] = {}
    output_state: dict[str, Any] = {}


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


class StorageMutation(BaseModel):
    op: str
    path: str


class StorageMutationEvent(BaseModel):
    execution_id: str
    org_prefix: str
    session_id: int | None = None
    mutations: list[StorageMutation]
