import { AuthorshipFields, GetPythonCodeRequest } from '@shared/models';

import { NodeIdentityDto } from './node-identity.model';

export interface PythonNode extends AuthorshipFields, NodeIdentityDto {
    id: number;
    node_name: string;
    graph: number;
    python_code: GetPythonCodeRequest;
    input_map: Record<string, unknown>;
    test_input: Record<string, string | number | boolean>;
    output_variable_path: string | null;
    metadata: Record<string, unknown>;
    use_storage?: boolean;
    created_at: string;
}
