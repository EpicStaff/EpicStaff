import { AuthorshipFields } from '@shared/models';

import { NodeIdentityDto } from './node-identity.model';

/** Backend DTO for GraphNote */
export interface GraphNote extends AuthorshipFields, NodeIdentityDto {
    id: number;
    created_at: string;
    node_name: string;
    graph: number;
    content: string;
    metadata: Record<string, unknown>;
}
