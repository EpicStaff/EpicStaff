export type ToolMode = 'allow' | 'deny';

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
    similarity_threshold: string;
}

export interface SurfaceKnowledge {
    collection: number;
    naive_search_config?: SurfaceNaiveSearchConfig | null;
    graph_basic_search_config?: unknown | null;
    graph_local_search_config?: unknown | null;
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

export interface SurfaceListItem {
    id: number;
    name: string;
}

export function toSurfaceListItem(s: Surface): SurfaceListItem {
    return { id: s.id, name: s.name };
}

// TODO(EST-2946): "Allow Collection Creation" has no backend field
