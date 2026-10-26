import { NodeModel } from '../../core/models/node.model';

export function toNodeMetadata(node: NodeModel): Record<string, unknown> {
    return {
        position: node.position,
        color: node.color,
        icon: node.icon,
        size: node.size,
    };
}
