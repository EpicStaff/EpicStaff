import { IPoint } from '@foblex/2d';

import { ConnectionModel } from '../models/connection.model';
import { BaseNodeModel } from '../models/node.model';
import { ViewPort } from '../models/port.model';

const EXIT_OFFSET = 40;
const ENTRY_OFFSET = 40;
const H_CLEARANCE = 20;
const MAX_LIFT = 260;

function getPortPosition(node: BaseNodeModel, port: ViewPort | undefined): IPoint {
    const { x, y } = node.position;
    const { width, height } = node.size;
    switch (port?.position) {
        case 'right':
            return { x: x + width, y: y + height / 2 };
        case 'top':
            return { x: x + width / 2, y: y };
        case 'bottom':
            return { x: x + width / 2, y: y + height };
        default:
            return { x, y: y + height / 2 }; // 'left' or undefined
    }
}

/**
 * Computes waypoints for a segment connection to arch above any intermediate
 * nodes whose bounding boxes overlap the connection's corridor.
 *
 * Returns two waypoints (the "column tops" of the arch) when avoidance is needed,
 * or null when the path is clear (caller should clear stale auto-waypoints).
 *
 * Only handles horizontal connections (left/right ports). Returns null for
 * top/bottom ports (vertical layout — not yet supported).
 */
export function computeSegmentAvoidanceWaypoints(
    connection: ConnectionModel,
    allNodes: BaseNodeModel[]
): IPoint[] | null {
    const sourceNode = allNodes.find((n) => n.id === connection.sourceNodeId);
    const targetNode = allNodes.find((n) => n.id === connection.targetNodeId);
    if (!sourceNode || !targetNode) return null;

    const sourcePort = sourceNode.ports?.find((p) => p.id === connection.sourcePortId);
    const targetPort = targetNode.ports?.find((p) => p.id === connection.targetPortId);

    // Skip vertical layout (top/bottom ports)
    if (
        sourcePort?.position === 'top' ||
        sourcePort?.position === 'bottom' ||
        targetPort?.position === 'top' ||
        targetPort?.position === 'bottom'
    ) {
        return null;
    }

    const sourcePt = getPortPosition(sourceNode, sourcePort);
    const targetPt = getPortPosition(targetNode, targetPort);

    // Column x positions (with exit/entry stubs)
    const sx2 = sourcePt.x + EXIT_OFFSET;
    const tx2 = targetPt.x - ENTRY_OFFSET;

    const corridorLeft = Math.min(sx2, tx2);
    const corridorRight = Math.max(sx2, tx2);
    const corridorTop = Math.min(sourcePt.y, targetPt.y);
    const corridorBottom = Math.max(sourcePt.y, targetPt.y);

    // Find nodes whose bounding boxes overlap the corridor (exclude source/target)
    const blockers = allNodes.filter((n) => {
        if (n.id === connection.sourceNodeId || n.id === connection.targetNodeId) return false;
        const nRight = n.position.x + n.size.width;
        const nBottom = n.position.y + n.size.height;
        return (
            n.position.x < corridorRight &&
            nRight > corridorLeft &&
            n.position.y < corridorBottom &&
            nBottom > corridorTop
        );
    });

    if (blockers.length === 0) return null;

    // Route above all blockers (iterative, same pattern as BackwardArcPathBuilder.avoidHorizontal)
    const cap = Math.min(sourcePt.y, targetPt.y) - MAX_LIFT;
    let routeY = corridorTop - H_CLEARANCE;

    for (let pass = 0; pass < 8; pass++) {
        let moved = false;
        for (const node of blockers) {
            const nBottom = node.position.y + node.size.height;
            if (nBottom < routeY || node.position.y > routeY) continue;
            const candidate = node.position.y - H_CLEARANCE;
            if (candidate < routeY) {
                routeY = candidate;
                moved = true;
            }
        }
        if (!moved) break;
    }

    routeY = Math.max(cap, routeY);

    // Two "column top" waypoints give a clean, predictable U-arch shape:
    //   source → exit stub → rise → horizontal top → descent → entry stub → target
    return [
        { x: sx2, y: routeY },
        { x: tx2, y: routeY },
    ];
}
