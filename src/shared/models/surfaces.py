from typing import Literal

from pydantic import BaseModel, ConfigDict

ToolModeLiteral = Literal["allow", "deny"]
StorageAccessLiteral = Literal["allow", "unset", "deny"]


class CombinedSurfacePythonToolData(BaseModel):
    python_tool: int
    mode: ToolModeLiteral

    model_config = ConfigDict(from_attributes=True)


class CombinedSurfaceMcpToolData(BaseModel):
    mcp_tool: int
    mode: ToolModeLiteral

    model_config = ConfigDict(from_attributes=True)


class CombinedSurfaceStorageItemData(BaseModel):
    storage_file: int
    can_list: StorageAccessLiteral = "unset"
    can_view: StorageAccessLiteral = "unset"
    can_edit: StorageAccessLiteral = "unset"
    can_delete: StorageAccessLiteral = "unset"

    model_config = ConfigDict(from_attributes=True)


class SurfaceNaiveSearchConfigData(BaseModel):
    search_limit: int = 3
    similarity_threshold: float = 0.20

    model_config = ConfigDict(from_attributes=True)


class SurfaceGraphBasicSearchConfigData(BaseModel):
    prompt: str | None = None
    k: int = 10
    max_context_tokens: int = 12000

    model_config = ConfigDict(from_attributes=True)


class SurfaceGraphLocalSearchConfigData(BaseModel):
    prompt: str | None = None
    text_unit_prop: float = 0.5
    community_prop: float = 0.15
    conversation_history_max_turns: int = 5
    top_k_entities: int = 10
    top_k_relationships: int = 10
    max_context_tokens: int = 12000

    model_config = ConfigDict(from_attributes=True)


class CombinedSurfaceKnowledgeData(BaseModel):
    collection: int
    naive_search_config: SurfaceNaiveSearchConfigData | None = None
    graph_basic_search_config: SurfaceGraphBasicSearchConfigData | None = None
    graph_local_search_config: SurfaceGraphLocalSearchConfigData | None = None

    model_config = ConfigDict(from_attributes=True)


class CombinedSurfaceData(BaseModel):
    instructions: str = ""
    python_tools: list[CombinedSurfacePythonToolData] = []
    mcp_tools: list[CombinedSurfaceMcpToolData] = []
    storage_items: list[CombinedSurfaceStorageItemData] = []
    knowledge: list[CombinedSurfaceKnowledgeData] = []

    model_config = ConfigDict(from_attributes=True)
