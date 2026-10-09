import { AuthorshipFields } from '@shared/models';

export interface StartNode extends AuthorshipFields {
    id: number;
    created_at: string;
    graph: number;
    node_name: string;
    variables: Record<string, unknown>; // This indicates variables is a JSON object
    metadata: Record<string, unknown>;
}
