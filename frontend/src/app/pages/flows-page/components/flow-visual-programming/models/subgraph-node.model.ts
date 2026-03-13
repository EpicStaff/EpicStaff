import { GetGraphLightRequest } from '../../../../../features/flows/models/graph.model';

export interface SubGraphNode {
    id: number;
    node_name: string;
    graph: number;
    subgraph: number;
    /** Nested light graph object (populated by backend serializer). */
    subgraph_detail?: GetGraphLightRequest;
    input_map: Record<string, any>;
    output_variable_path: string | null;
    metadata: Record<string, any>;
}

export interface CreateSubGraphNodeRequest {
    node_name: string;
    graph: number;
    subgraph: number;
    input_map: Record<string, any>;
    output_variable_path: string | null;
    metadata?: Record<string, any>;
}

export interface UpdateSubGraphNodeRequest {
    node_name?: string;
    graph?: number;
    subgraph?: number;
    input_map?: Record<string, any>;
    output_variable_path?: string | null;
}

