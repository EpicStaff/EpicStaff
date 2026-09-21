import { IPoint } from '@foblex/2d';

import { NodeType } from '../enums/node-type';
import { ClassificationDecisionTableNodeModel, DecisionTableNodeModel, NodeModel } from '../models/node.model';
import { getClassificationTableVisualHeight, getDecisionTableVisualHeight } from './node-size.util';

export interface CollisionBounds {
    width: number;
    height: number;
    offsetX: number;
    offsetY: number;
}

export const GRID_CELL_SIZE = 20;

const MAX_SEARCH_RADIUS = 40;

export function snapToGrid(value: number): number {
    return Math.round(value / GRID_CELL_SIZE) * GRID_CELL_SIZE;
}

export function snapPointToGrid(point: IPoint): IPoint {
    return {
        x: snapToGrid(point.x),
        y: snapToGrid(point.y),
    };
}

export function getCollisionBounds(node: Pick<NodeModel, 'type' | 'size' | 'data'>): CollisionBounds {
    switch (node.type) {
        case NodeType.EDGE:
            return { width: 308, height: 196, offsetX: 5, offsetY: -12 };

        case NodeType.TABLE: {
            const conditionGroups = (node as DecisionTableNodeModel).data.table?.condition_groups ?? [];
            return {
                width: node.size.width + 40,
                height: getDecisionTableVisualHeight(conditionGroups) + 30,
                offsetX: -20,
                offsetY: -15,
            };
        }

        case NodeType.CLASSIFICATION_TABLE: {
            const conditionGroups = (node as ClassificationDecisionTableNodeModel).data.table?.condition_groups ?? [];
            return {
                width: node.size.width + 40,
                height: getClassificationTableVisualHeight(conditionGroups) + 30,
                offsetX: -20,
                offsetY: -15,
            };
        }

        default:
            return {
                width: node.size.width + 30,
                height: node.size.height + 30,
                offsetX: -15,
                offsetY: -15,
            };
    }
}

/**
 * A node's true geometric bounds — its real `size`, with no padding/inflation. Unlike
 * `getCollisionBounds()`, this is only meant for contexts where the user is intentionally
 * placing a node (e.g. drag-end), so it can end up flush against another node instead of
 * "bouncing" away from an artificial margin. Node creation/paste must keep using
 * `getCollisionBounds()` so newly placed nodes still land with breathing room.
 */
export function getExactBounds(node: Pick<NodeModel, 'size'>): CollisionBounds {
    return {
        width: node.size.width,
        height: node.size.height,
        offsetX: 0,
        offsetY: 0,
    };
}

export function hasCollision(
    pos: IPoint,
    bounds: CollisionBounds,
    otherNodes: NodeModel[],
    getOtherBounds: (node: NodeModel) => CollisionBounds = getCollisionBounds
): boolean {
    return otherNodes.some((n) => rectOverlaps(pos, bounds, n.position, getOtherBounds(n)));
}

export function findNearestFreePosition(
    proposed: IPoint,
    bounds: CollisionBounds,
    otherNodes: NodeModel[],
    getOtherBounds: (node: NodeModel) => CollisionBounds = getCollisionBounds
): IPoint {
    if (!hasCollision(proposed, bounds, otherNodes, getOtherBounds)) return proposed;

    const candidates: Array<[number, number]> = [];
    for (let dx = -MAX_SEARCH_RADIUS; dx <= MAX_SEARCH_RADIUS; dx++) {
        for (let dy = -MAX_SEARCH_RADIUS; dy <= MAX_SEARCH_RADIUS; dy++) {
            if (dx === 0 && dy === 0) continue;
            candidates.push([dx, dy]);
        }
    }
    candidates.sort((a, b) => a[0] * a[0] + a[1] * a[1] - (b[0] * b[0] + b[1] * b[1]));

    for (const [dx, dy] of candidates) {
        const candidate: IPoint = {
            x: proposed.x + dx * GRID_CELL_SIZE,
            y: proposed.y + dy * GRID_CELL_SIZE,
        };
        if (!hasCollision(candidate, bounds, otherNodes, getOtherBounds)) return candidate;
    }

    return proposed;
}

export function resolveOverlapsForNode(anchorId: string, allNodes: NodeModel[]): NodeModel[] {
    const anchor = allNodes.find((n) => n.id === anchorId);
    if (!anchor) return [];

    const anchorBounds = getCollisionBounds(anchor);
    const workingNodes = [...allNodes];
    const movedNodes: NodeModel[] = [];

    const sortedOthers = workingNodes.filter((n) => n.id !== anchorId).sort((a, b) => a.position.y - b.position.y);

    for (const node of sortedOthers) {
        const isOverlapping = rectOverlaps(node.position, getCollisionBounds(node), anchor.position, anchorBounds);
        if (!isOverlapping) continue;

        const freePos = findNearestFreePosition(
            node.position,
            getCollisionBounds(node),
            workingNodes.filter((n) => n.id !== node.id)
        );

        if (freePos.x !== node.position.x || freePos.y !== node.position.y) {
            const updatedNode = { ...node, position: freePos };
            const idx = workingNodes.findIndex((n) => n.id === node.id);
            workingNodes[idx] = updatedNode;
            movedNodes.push(updatedNode);
        }
    }

    return movedNodes;
}

// TODO candidate to remove if nobody works on it

// export function resolveDraggedNodePositions(
//     allNodes: NodeModel[],
//     draggedNodeIds: Set<string>,
//     runtimePositions: Map<string, IPoint>
// ): NodeModel[] {
//     const updatedNodesById = new Map<string, NodeModel>();
//     const workingNodes = allNodes.map((node) => {
//         const runtimePosition = runtimePositions.get(node.id);
//         if (!runtimePosition || !draggedNodeIds.has(node.id)) {
//             return node;
//         }

//         const updatedNode = { ...node, position: runtimePosition };
//         updatedNodesById.set(node.id, updatedNode);
//         return updatedNode;
//     });

//     for (const id of draggedNodeIds) {
//         const current = workingNodes.find((node) => node.id === id);
//         if (!current) continue;

//         const freePos = findNearestFreePosition(
//             current.position,
//             getCollisionBounds(current),
//             workingNodes.filter((node) => node.id !== id)
//         );

//         if (freePos.x !== current.position.x || freePos.y !== current.position.y) {
//             const updatedNode = { ...current, position: freePos };
//             const index = workingNodes.findIndex((node) => node.id === id);
//             if (index >= 0) {
//                 workingNodes[index] = updatedNode;
//             }
//             updatedNodesById.set(id, updatedNode);
//         }
//     }

//     return Array.from(updatedNodesById.values());
// }

function rectOverlaps(aPos: IPoint, aBounds: CollisionBounds, bPos: IPoint, bBounds: CollisionBounds): boolean {
    const aLeft = aPos.x + aBounds.offsetX;
    const aTop = aPos.y + aBounds.offsetY;
    const aRight = aLeft + aBounds.width;
    const aBottom = aTop + aBounds.height;

    const bLeft = bPos.x + bBounds.offsetX;
    const bTop = bPos.y + bBounds.offsetY;
    const bRight = bLeft + bBounds.width;
    const bBottom = bTop + bBounds.height;

    return aLeft < bRight && aRight > bLeft && aTop < bBottom && aBottom > bTop;
}
