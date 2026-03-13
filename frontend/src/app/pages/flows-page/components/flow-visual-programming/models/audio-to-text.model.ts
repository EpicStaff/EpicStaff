export interface GetAudioToTextNodeRequest {
    id: number;
    node_name: string;
    graph: number;
    input_map: Record<string, any>;
    output_variable_path: string | null;
    metadata: Record<string, any>;
}

export interface CreateAudioToTextNodeRequest {
    node_name: string;
    graph: number;
    input_map: Record<string, any>;
    output_variable_path: string | null;
    metadata?: Record<string, any>;
}
