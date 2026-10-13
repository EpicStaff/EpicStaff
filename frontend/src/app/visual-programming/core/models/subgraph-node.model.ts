import { AuthorshipFields } from '@shared/models';

import { GetGraphLightRequest } from '../../../features/flows/models/graph.model';
import { NodeIdentityDto } from './node-identity.model';

export interface SubGraphNode extends AuthorshipFields, NodeIdentityDto {
    id: number;
    created_at: string;
    node_name: string;
    graph: number;
    /** Null when the referenced flow was deleted (`on_delete=SET_NULL`). */
    subgraph: number | null;
    /** Nested light graph object (populated by backend serializer). */
    subgraph_detail?: GetGraphLightRequest | null;
    input_map: Record<string, unknown>;
    output_variable_path: string | null;
    metadata: Record<string, unknown>;
}
