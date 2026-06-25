import { CustomPythonCode, GetPythonCodeRequest } from '../../../../../features/tools/models/python-code.model';

export interface ConditionalEdge {
    id: number;
    graph: number;
    source_node_id: number;
    python_code: GetPythonCodeRequest;
    input_map: Record<string, unknown>;
    metadata: Record<string, unknown>;
}

export interface CustomConditionalEdgeModelForNode {
    id?: number;
    source: string | null;
    then: string | null;
    python_code: CustomPythonCode;
    input_map: Record<string, unknown>;
}
