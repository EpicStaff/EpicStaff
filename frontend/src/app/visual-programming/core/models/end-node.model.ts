import { AuthorshipFields } from '@shared/models';

import { NodeIdentityDto } from './node-identity.model';

export interface EndNode extends AuthorshipFields, NodeIdentityDto {
    id: number;
    created_at: string;
    graph: number;
    output_map: Record<string, unknown>;
    metadata: Record<string, unknown>;
    node_name?: string; // Added by serializer (always "__end_node__" but may vary in UI)
}
