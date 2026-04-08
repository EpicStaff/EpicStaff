import { NODE_TYPE_PREFIXES } from '../enums/node-type-prefixes';
import { NodeModel } from '../models/node.model';

export function getMinimapClassForNode(node: NodeModel): string[] {
    if (!node.type) {
        return [];
    }

    const className: string = NODE_TYPE_PREFIXES[node.type].replace(/\s+/g, '-');
    return [className];
}
