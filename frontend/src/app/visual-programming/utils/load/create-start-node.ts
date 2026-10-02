import { NODE_COLORS, NODE_ICONS, NodeType } from '@shared/models';
import { generateUuid } from '@shared/utils';

import { getDefaultNodeSize } from '../../core/helpers/node-size.util';
import { StartNodeModel } from '../../core/models/node.model';

export function createStartNode(): StartNodeModel {
    return {
        id: generateUuid(),
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
