import { NodeType } from '@shared/models';

import { FlowModel } from '../../core/models/flow.model';

export function hasStartNode(flowModel: FlowModel): boolean {
    return flowModel.nodes.some((n) => n.type === NodeType.START);
}
