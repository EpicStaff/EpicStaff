export interface SubGraphNode {
    id: number;
    node_name: string;
    graph: number;
    subgraph: number;
    input_map: Record<string, any>;
    output_variable_path: string | null;
}

export interface CreateSubGraphNodeRequest {
    node_name: string;
    graph: number;
    subgraph: number;
    input_map: Record<string, any>;
    output_variable_path: string | null;
}

export interface UpdateSubGraphNodeRequest {
    node_name?: string;
    graph?: number;
    subgraph?: number;
    input_map?: Record<string, any>;
    output_variable_path?: string | null;
}

