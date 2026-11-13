import { AuthorshipFields } from '@shared/models';

import { NodeIdentityDto } from './node-identity.model';
import { NumberedNodeDto } from './numbered-node-dto.model';

export interface GetAudioToTextNodeRequest extends AuthorshipFields, NodeIdentityDto, NumberedNodeDto {
    id: number;
    created_at: string;
    node_name: string;
    graph: number;
    input_map: Record<string, unknown>;
    output_variable_path: string | null;
    metadata: Record<string, unknown>;
}
