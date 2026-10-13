import { AuthorshipFields, GetPythonCodeRequest } from '@shared/models';

export interface PythonNode extends AuthorshipFields {
    id: number;
    node_name: string;
    graph: number;
    python_code: GetPythonCodeRequest;
    input_map: Record<string, unknown>;
    test_input: Record<string, string | number | boolean>;
    output_variable_path: string | null;
    metadata: Record<string, unknown>;
    use_storage?: boolean;
    /**
     * Minutes one sandbox execution of the node's code may run (1 to the sandbox ceiling). The API always sends
     * it; a version snapshot saved before nodes had a timeout does not.
     */
    execution_timeout?: number;
    created_at: string;
}
