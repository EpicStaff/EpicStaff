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


class SurfaceGraphGlobalSearchConfigData(BaseModel):
    map_prompt: str | None = None
    reduce_prompt: str | None = None
    knowledge_prompt: str | None = None
    max_context_tokens: int = 12000
    data_max_tokens: int = 12000
    map_max_length: int = 1000
    reduce_max_length: int = 2000
    dynamic_community_selection: bool = False
    dynamic_search_threshold: int = 1
    dynamic_search_keep_parent: bool = False
    dynamic_search_num_repeats: int = 1
    dynamic_search_use_summary: bool = False
    dynamic_search_max_level: int = 2

    model_config = ConfigDict(from_attributes=True)


class SurfaceGraphDriftSearchConfigData(BaseModel):
    prompt: str | None = None
    reduce_prompt: str | None = None
    data_max_tokens: int = 12000
    reduce_max_tokens: int | None = None
    reduce_temperature: float = 0.0
    reduce_max_completion_tokens: int | None = None
    concurrency: int = 32
    drift_k_followups: int = 20
    primer_folds: int = 5
    primer_llm_max_tokens: int = 12000
    n_depth: int = 3
    community_level: int = 2
    local_search_text_unit_prop: float = 0.9
    local_search_community_prop: float = 0.1
    local_search_top_k_mapped_entities: int = 10
    local_search_top_k_relationships: int = 10
    local_search_max_data_tokens: int = 12000
    local_search_temperature: float = 0.0
    local_search_top_p: float = 1.0
    local_search_n: int = 1
    local_search_llm_max_gen_tokens: int | None = None
    local_search_llm_max_gen_completion_tokens: int | None = None

    model_config = ConfigDict(from_attributes=True)


class CombinedSurfaceKnowledgeData(BaseModel):
    collection: int
    naive_search_config: SurfaceNaiveSearchConfigData | None = None
    graph_basic_search_config: SurfaceGraphBasicSearchConfigData | None = None
    graph_local_search_config: SurfaceGraphLocalSearchConfigData | None = None
    graph_global_search_config: SurfaceGraphGlobalSearchConfigData | None = None
    graph_drift_search_config: SurfaceGraphDriftSearchConfigData | None = None

    model_config = ConfigDict(from_attributes=True)


class CombinedSurfaceData(BaseModel):
    instructions: str = ""
    python_tools: list[CombinedSurfacePythonToolData] = []
    mcp_tools: list[CombinedSurfaceMcpToolData] = []
    storage_items: list[CombinedSurfaceStorageItemData] = []
    knowledge: list[CombinedSurfaceKnowledgeData] = []

    model_config = ConfigDict(from_attributes=True)
