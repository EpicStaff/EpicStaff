export type ToolMode = 'allow' | 'deny';

export interface SurfaceSaveError {
    surfaceId: number;
    tick: number;
}

export type PermTriState = 'allow' | 'unset' | 'deny';

export interface SurfacePythonTool {
    python_tool: number;
    mode: ToolMode;
}

export interface SurfaceMcpTool {
    mcp_tool: number;
    mode: ToolMode;
}

export interface SurfaceStorageItem {
    storage_file: number;
    can_list: PermTriState;
    can_view: PermTriState;
    can_edit: PermTriState;
    can_delete: PermTriState;
}

export interface SurfaceNaiveSearchConfig {
    search_limit: number;
    similarity_threshold: string | number;
}

export interface SurfaceGraphBasicSearchConfig {
    prompt?: string | null;
    k: number;
    max_context_tokens: number;
}

export interface SurfaceGraphLocalSearchConfig {
    prompt?: string | null;
    text_unit_prop: number;
    community_prop: number;
    conversation_history_max_turns: number;
    top_k_entities: number;
    top_k_relationships: number;
    max_context_tokens: number;
}

export interface SurfaceKnowledge {
    collection: number;
    naive_search_config?: SurfaceNaiveSearchConfig | null;
    graph_basic_search_config?: SurfaceGraphBasicSearchConfig | null;
    graph_local_search_config?: SurfaceGraphLocalSearchConfig | null;
}

export interface Surface {
    id: number;
    organization: number;
    name: string;
    description: string;
    instructions: string;
    owner_agent: number | null;
    allow_creation: boolean;
    python_tools: SurfacePythonTool[];
    mcp_tools: SurfaceMcpTool[];
    storage_items: SurfaceStorageItem[];
    knowledge: SurfaceKnowledge[];
    created_at: string;
    updated_at: string;
}

export interface CreateSurfaceRequest {
    name: string;
    description?: string;
    instructions?: string;
    owner_agent?: number | null;
    allow_creation?: boolean;
    python_tools?: SurfacePythonTool[];
    mcp_tools?: SurfaceMcpTool[];
    storage_items?: SurfaceStorageItem[];
    knowledge?: SurfaceKnowledge[];
}

export type UpdateSurfaceRequest = CreateSurfaceRequest;
export type PartialUpdateSurfaceRequest = Partial<CreateSurfaceRequest>;

export interface CombinedSurface {
    instructions: string;
    allow_creation: boolean;
    python_tools: SurfacePythonTool[];
    mcp_tools: SurfaceMcpTool[];
    storage_items: SurfaceStorageItem[];
    knowledge: SurfaceKnowledge[];
}
