import {
    SurfaceKnowledge,
    SurfaceMcpTool,
    SurfacePythonTool,
    SurfaceStorageItem,
} from '../../../../../features/agent-definitions/models/surface.model';

/**
 * Write-shape entries used by `InlineSurface`'s tool/storage/knowledge lists.
 * These are field-for-field identical to the regular `Surface` sub-types on the backend
 * (the `inline_surface` write serializer reuses the `Surface` write serializers), so we
 * reuse the `Surface` sub-types directly rather than redefining narrower shapes.
 */
export type InlineSurfacePythonTool = SurfacePythonTool;

export type InlineSurfaceMcpTool = SurfaceMcpTool;

export type InlineSurfaceStorageItem = SurfaceStorageItem;

export type InlineSurfaceKnowledge = SurfaceKnowledge;

/**
 * The task-local ("Local surface") nested object. Independent of `surface_list` (which
 * references existing catalog `Surface` ids). `null` means no local surface; omitting the
 * field on a PATCH-style update leaves it untouched server-side; a full object replaces it.
 * `id`/`created_at`/`updated_at` are read-only (present on read, absent when creating).
 *
 * Field-for-field identical to `Surface` EXCEPT it has no `name`, `organization`, or
 * `owner_agent` (per the backend `inline_surface` write serializer, which reuses the
 * regular `Surface` write serializers).
 */
export interface InlineSurface {
    id?: number;
    instructions: string;
    python_tools: InlineSurfacePythonTool[];
    mcp_tools: InlineSurfaceMcpTool[];
    storage_items: InlineSurfaceStorageItem[];
    knowledge: InlineSurfaceKnowledge[];
    created_at?: string;
    updated_at?: string;
}

export interface TaskNode {
    id: number;
    created_at: string;
    updated_at: string;
    metadata: Record<string, unknown>;
    node_name: string;
    graph: number;
    input_map: Record<string, unknown>;
    output_variable_path: string | null;
    instructions: string;
    /** Non-nullable JSONField on the backend — `{}` means "no schema". Never `null`. */
    output_schema: Record<string, unknown>;
    remember_output: boolean;
    agent_definition: number | null;
    content_hash?: string;
    /** Flat array of existing catalog `Surface` ids (agent-owned + shared). */
    surface_list: number[];
    /** Task-local nested surface, or `null` when absent. */
    inline_surface: InlineSurface | null;
}

export interface CreateTaskNodeRequest {
    node_name: string;
    graph: number;
    input_map: Record<string, unknown>;
    output_variable_path: string | null;
    instructions: string;
    output_schema?: Record<string, unknown>;
    remember_output?: boolean;
    agent_definition: number | null;
    metadata?: Record<string, unknown>;
    surface_list?: number[];
    inline_surface?: InlineSurface | null;
}

/**
 * UI-facing data held on the Task node's canvas model (`TaskNodeModel.data`).
 * Mirrors the flat `TaskNode` DTO fields plus a display-only `name`, matching the
 * `CustomPythonCode.name` convention used by sibling node types.
 */
export interface TaskNodeData {
    name: string;
    instructions: string;
    output_schema: Record<string, unknown>;
    output_schema_invalid?: boolean;
    remember_output: boolean;
    agent_definition: number | null;
    content_hash?: string;
    surface_list: number[];
    inline_surface: InlineSurface | null;
}
