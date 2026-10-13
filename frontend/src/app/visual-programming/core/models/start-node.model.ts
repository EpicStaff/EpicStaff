import { AuthorshipFields } from '@shared/models';

import { NodeIdentityDto } from './node-identity.model';

export interface StartNode extends AuthorshipFields, NodeIdentityDto {
    id: number;
    created_at: string;
    graph: number;
    node_name: string;
    variables: Record<string, unknown>; // This indicates variables is a JSON object
    metadata: Record<string, unknown>;
}
