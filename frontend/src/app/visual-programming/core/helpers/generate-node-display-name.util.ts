import { NodeType } from '@shared/models';

import { NODE_TYPE_PREFIXES } from '../enums/node-type-prefixes';

/** The name a new node of `type` starts with. The node number is never part of it: the badge shows that. */
export function generateNodeDisplayName(type: NodeType): string {
    if (type === NodeType.END) {
        return '__end_node__';
    }
    if (type === NodeType.START) {
        return 'Start';
    }
    return NODE_TYPE_PREFIXES[type];
}
