export interface StartNode {
    id: number;
    graph: number;
    node_name: string;
    variables: Record<string, unknown>; // This indicates variables is a JSON object
    metadata: Record<string, unknown>;
}

export interface CreateStartNodeRequest {
    graph: number;
    variables: Record<string, unknown>; // This indicates variables is a JSON object
    metadata?: Record<string, unknown>;
}
