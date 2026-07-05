import { GetPythonCodeRequest } from '../../../../../features/tools/models/python-code.model';

export interface PythonNode {
    id: number;
    node_name: string;
    graph: number;
    python_code: GetPythonCodeRequest;
    input_map: Record<string, unknown>;
    test_input: Record<string, string | number | boolean>;
    output_variable_path: string | null;
    stream_config?: Record<string, boolean>;
    metadata: Record<string, unknown>;
    use_storage?: boolean;
}
