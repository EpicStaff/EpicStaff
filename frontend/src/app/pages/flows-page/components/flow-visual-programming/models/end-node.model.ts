export interface EndNode {
    id: number;
    graph: number;
    output_map: Record<string, unknown>;
    metadata: Record<string, unknown>;
    node_name?: string; // Added by serializer (always "__end_node__" but may vary in UI)
}

export interface UpdateEndNodeRequest {
    output_map: Record<string, unknown>;
}

export interface CreateEndNodeRequest {
    graph: number;
    output_map: Record<string, unknown>;
    metadata?: Record<string, unknown>;
}
