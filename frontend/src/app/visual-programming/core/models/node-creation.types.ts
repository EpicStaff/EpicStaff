import { NodeType } from '@shared/models';

import { NodeModel } from './node.model';

export interface CreateNodeRequest {
    type: NodeType;
    overrides?: Partial<NodeModel>;
    /** When true and type is NOTE, the flow enters area-draw mode instead of placing immediately. */
    areaSelection?: boolean;
}
