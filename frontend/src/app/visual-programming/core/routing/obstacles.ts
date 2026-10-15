import { NodeType } from '@shared/models';

import { getCollisionBounds } from '../helpers/node-placement.utils';
import { NodeModel } from '../models/node.model';

export interface Rect {
    left: number;
    top: number;
    right: number;
    bottom: number;
}

/**
 * How far a wire keeps above and below a node: one wire fits in a 20-px gap between two
 * stacked nodes (the return leg between them, and the layout's minimum gap). Left and right the collision padding stays
 * (15, 20 for tables): the port markers stick out 12 to 14 px from the sides.
 */
export const WIRE_CLEARANCE = 10;

/** A node's padded box on the canvas; tables use their visual height, EDGE its fixed box. */
export function obstacleRect(node: NodeModel): Rect {
    const bounds = getCollisionBounds(node);
    const left = node.position.x + bounds.offsetX;
    const right = left + bounds.width;
    if (node.type === NodeType.EDGE) {
        const top = node.position.y + bounds.offsetY;
        return { left, top, right, bottom: top + bounds.height };
    }
    // The collision bounds pad the drawn box by -offsetY above and as much below.
    const drawnHeight = bounds.height + 2 * bounds.offsetY;
    const top = node.position.y - WIRE_CLEARANCE;
    return { left, top, right, bottom: node.position.y + drawnHeight + WIRE_CLEARANCE };
}

/** Every node a wire must route around, keyed by node id. NOTE nodes are not obstacles. */
export function routingObstacles(nodes: NodeModel[]): Map<string, Rect> {
    const obstacles = new Map<string, Rect>();
    for (const node of nodes) {
        if (node.type !== NodeType.NOTE) obstacles.set(node.id, obstacleRect(node));
    }
    return obstacles;
}
