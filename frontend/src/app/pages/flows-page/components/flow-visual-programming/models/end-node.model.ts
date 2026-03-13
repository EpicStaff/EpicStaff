export interface EndNode {
    id: number;
    graph: number;
    output_map: Record<string, any>;
    metadata: Record<string, any>;
    node_name?: string; // Added by serializer (always "__end_node__" but may vary in UI)
}

export interface UpdateEndNodeRequest {
    output_map: Record<string, any>;
}

export interface CreateEndNodeRequest {
    graph: number;
    output_map: Record<string, any>;
    metadata?: Record<string, any>;
}
