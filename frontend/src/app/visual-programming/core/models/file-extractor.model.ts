import { AuthorshipFields } from '@shared/models';

export interface GetFileExtractorNodeRequest extends AuthorshipFields {
    id: number;
    created_at: string;
    node_name: string;
    graph: number;
    input_map: Record<string, unknown>;
    output_variable_path: string | null;
    metadata: Record<string, unknown>;
}
