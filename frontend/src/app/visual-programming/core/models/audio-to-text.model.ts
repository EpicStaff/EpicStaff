import { AuthorshipFields } from '@shared/models';

import { NodeIdentityDto } from './node-identity.model';

export interface GetAudioToTextNodeRequest extends AuthorshipFields, NodeIdentityDto {
    id: number;
    created_at: string;
    node_name: string;
    graph: number;
    input_map: Record<string, unknown>;
    output_variable_path: string | null;
    metadata: Record<string, unknown>;
}
