import { AuthorshipFields } from '@shared/models';

/** Backend DTO for GraphNote */
export interface GraphNote extends AuthorshipFields {
    id: number;
    created_at: string;
    node_name: string;
    graph: number;
    content: string;
    metadata: Record<string, unknown>;
}
