import { InlineSurface } from './task-node.model';

/**
 * Read-shape of a single task belonging to an Agent Node, as returned by
 * `GET /graphs/:id/` under `agent_node_list[].tasks[]`.
 */
export interface AgentNodeTaskDto {
    id: number;
    name: string;
    order: number;
    instructions: string;
    /** Non-nullable JSONField on the backend — `{}` means "no schema". Never `null`. */
    output_schema: Record<string, unknown>;
    /** Backward-only refs to sibling tasks (strictly lower `order`) within the same node. */
    context_tasks: number[];
    created_at?: string;
    updated_at?: string;
}

export interface AgentNodeTaskWrite {
    temp_id?: string;
    id?: number;
    name: string;
    order: number;
    instructions: string;
    output_schema: Record<string, unknown>;
    /** Refs to NEW sibling tasks (identified by their `temp_id`). */
    context_task_temp_ids?: string[];
    /** Refs to EXISTING sibling tasks (identified by their backend `id`). */
    context_task_ids?: number[];
}

export interface AgentNode {
    id: number;
    created_at?: string;
    updated_at?: string;
    metadata: Record<string, unknown>;
    node_name: string;
    graph?: number;
    input_map: Record<string, unknown>;
    output_variable_path: string | null;
    agent_definition: number | null;
    surface_list: number[];
    tasks: AgentNodeTaskDto[];
    inline_surface: InlineSurface | null;
    content_hash?: string;
}

export interface CreateAgentNodeRequest {
    temp_id?: string;
    id?: number;
    node_name: string;
    agent_definition: number | null;
    input_map: Record<string, unknown>;
    output_variable_path: string | null;
    surface_list: number[];
    tasks: AgentNodeTaskWrite[];
    inline_surface: InlineSurface | null;
    metadata?: Record<string, unknown>;
}

export interface AgentNodeTaskUi {
    id?: number;
    tempId: string;
    name: string;
    instructions: string;
    output_schema: Record<string, unknown>;
    output_schema_invalid?: boolean;
    contextRefs: Array<{ id?: number; tempId?: string }>;
}

export interface AgentNodeData {
    name: string;
    agent_definition: number | null;
    surface_list: number[];
    inline_surface: InlineSurface | null;
    tasks: AgentNodeTaskUi[];
}
