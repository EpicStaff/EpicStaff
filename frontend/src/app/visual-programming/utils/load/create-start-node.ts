import { generateUuid } from '@shared/utils';

import { NODE_COLORS, NODE_ICONS } from '../../core/enums/node-config';
import { NodeType } from '../../core/enums/node-type';
import { getDefaultNodeSize } from '../../core/helpers/node-size.util';
import { StartNodeModel } from '../../core/models/node.model';

export function tempStartNodeId(graphId: number): string {
    const n = graphId.toString(16).padStart(12, '0');
    return `00000000-0000-4000-ffff-${n}`;
}

export function createStartNode(graphId?: number): StartNodeModel {
    return {
        id: graphId != null ? tempStartNodeId(graphId) : generateUuid(),
        backendId: null,
        type: NodeType.START,
        node_name: '__start__',
        data: { initialState: {} },
        position: { x: 0, y: 0 },
        ports: null,
        color: NODE_COLORS[NodeType.START],
        icon: NODE_ICONS[NodeType.START],
        input_map: {},
        output_variable_path: null,
        size: getDefaultNodeSize(NodeType.START),
    };
}
