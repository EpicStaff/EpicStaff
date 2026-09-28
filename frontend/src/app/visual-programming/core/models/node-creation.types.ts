import { NodeType } from '@shared/models';

import { NodeModel } from './node.model';

export interface CreateNodeRequest {
    type: NodeType;
    overrides?: Partial<NodeModel>;
}
