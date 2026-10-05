import { AuthorshipFields } from '@shared/models';

export interface StartNode extends AuthorshipFields {
    id: number;
    graph: number;
    node_name: string;
    variables: Record<string, unknown>; // This indicates variables is a JSON object
    metadata: Record<string, unknown>;
}
