import { IPoint } from '@foblex/2d';

import { getPortPosition } from '../geometry/port-position';
import { isBackwardWire, isStacked } from '../geometry/wire-direction';
import { ConnectionModel } from '../models/connection.model';
import { NodeModel } from '../models/node.model';
import { computeForwardControlPoints } from './curved-route-shapes';
import { obstacleRect, Rect, routingObstacles, WIRE_CLEARANCE } from './obstacles';
import { resolveWireEnds } from './route-all';

/**
 * Curved-wire router: returns interior through-points for each connection.
 * The caller (CurvedPathBuilder) interpolates these into smooth Bezier curves
 * via Catmull-Rom. Source/target port positions are NOT included in the output —
 * the builder adds those itself.
 *
 * Mirrors the signature and return shape of `routeAll()`.
 */

const EXIT_STUB_MINIMUM = 40;
const BACKWARD_LOOP_CLEARANCE_MULTIPLIER = 4;
const BACKWARD_STUB_CLEARANCE_MULTIPLIER = 3;
const DETOUR_CLEARANCE_MULTIPLIER = 2;

export function routeAllCurved(nodes: NodeModel[], connections: ConnectionModel[]): Map<string, IPoint[]> {
    const nodesById = new Map(nodes.map((node) => [node.id, node]));
    const obstaclesById = routingObstacles(nodes);
    const routes = new Map<string, IPoint[]>();

    for (const connection of connections) {
        const ends = resolveWireEnds(connection, nodesById);
        if (!ends) continue;

        if (connection.userAdjustedWaypoints) continue;

        const source = getPortPosition(ends.sourceNode, ends.sourcePort);
        const target = getPortPosition(ends.targetNode, ends.targetPort);
        const sourceRect = obstaclesById.get(ends.sourceNode.id) ?? obstacleRect(ends.sourceNode);
        const targetRect = obstaclesById.get(ends.targetNode.id) ?? obstacleRect(ends.targetNode);

        const stacked = isStacked(sourceRect, targetRect);
        const backward = isBackwardWire(source, target, sourceRect, targetRect);

        let throughPoints: IPoint[];

        if (backward) {
            throughPoints = routeBackward(source, target, sourceRect, targetRect, obstaclesById, connection);
        } else if (stacked) {
            throughPoints = routeStacked(source, target, sourceRect, targetRect);
        } else {
            throughPoints = routeForward(source, target, obstaclesById, connection);
        }

        routes.set(connection.id, throughPoints);
    }

    return routes;
}

// ---------------------------------------------------------------------------
// Forward connections: source is left of target
// ---------------------------------------------------------------------------

function routeForward(
    source: IPoint,
    target: IPoint,
    obstaclesById: Map<string, Rect>,
    connection: ConnectionModel
): IPoint[] {
    const initialPoints = computeForwardControlPoints(source, target);

    const blockingObstacles = findObstaclesBetween(
        source,
        target,
        obstaclesById,
        connection.sourceNodeId,
        connection.targetNodeId
    );

    if (blockingObstacles.length === 0) {
        return initialPoints;
    }

    return routeAroundObstacles(source, target, initialPoints, blockingObstacles);
}

// ---------------------------------------------------------------------------
// Backward connections: target input is left of source output — loop over top
// ---------------------------------------------------------------------------

function routeBackward(
    source: IPoint,
    target: IPoint,
    sourceRect: Rect,
    targetRect: Rect,
    obstaclesById: Map<string, Rect>,
    connection: ConnectionModel
): IPoint[] {
    const exitOffset = Math.max(EXIT_STUB_MINIMUM, WIRE_CLEARANCE * BACKWARD_STUB_CLEARANCE_MULTIPLIER);
    const entryOffset = Math.max(EXIT_STUB_MINIMUM, WIRE_CLEARANCE * BACKWARD_STUB_CLEARANCE_MULTIPLIER);

    const exitStub: IPoint = { x: source.x + exitOffset, y: source.y };
    const entryStub: IPoint = { x: target.x - entryOffset, y: target.y };

    let loopY = Math.min(sourceRect.top, targetRect.top) - WIRE_CLEARANCE * BACKWARD_LOOP_CLEARANCE_MULTIPLIER;

    // Check for obstacles along the loop path and push loopY upward if needed.
    const loopLeft = Math.min(entryStub.x, exitStub.x);
    const loopRight = Math.max(entryStub.x, exitStub.x);

    for (const [nodeId, rect] of obstaclesById) {
        if (nodeId === connection.sourceNodeId || nodeId === connection.targetNodeId) continue;
        if (rect.right < loopLeft || rect.left > loopRight) continue;
        if (rect.top < loopY + WIRE_CLEARANCE) {
            loopY = rect.top - WIRE_CLEARANCE * BACKWARD_LOOP_CLEARANCE_MULTIPLIER;
        }
    }

    return [exitStub, { x: exitStub.x, y: loopY }, { x: entryStub.x, y: loopY }, entryStub];
}

// ---------------------------------------------------------------------------
// Stacked nodes: overlapping in X
// ---------------------------------------------------------------------------

function routeStacked(source: IPoint, target: IPoint, sourceRect: Rect, targetRect: Rect): IPoint[] {
    const [upperRect, lowerRect] =
        sourceRect.top <= targetRect.top ? [sourceRect, targetRect] : [targetRect, sourceRect];
    const gapBetween = lowerRect.top - upperRect.bottom;

    if (gapBetween >= 2 * WIRE_CLEARANCE) {
        // Route through the gap between stacked nodes.
        const gapY = upperRect.bottom + gapBetween / 2;
        const exitOffset = Math.max(EXIT_STUB_MINIMUM, WIRE_CLEARANCE * BACKWARD_STUB_CLEARANCE_MULTIPLIER);
        const entryOffset = Math.max(EXIT_STUB_MINIMUM, WIRE_CLEARANCE * BACKWARD_STUB_CLEARANCE_MULTIPLIER);

        const exitStub: IPoint = { x: source.x + exitOffset, y: source.y };
        const entryStub: IPoint = { x: target.x - entryOffset, y: target.y };

        return [exitStub, { x: exitStub.x, y: gapY }, { x: entryStub.x, y: gapY }, entryStub];
    }

    // No gap — route around above or below, whichever is shorter.
    const aboveY = Math.min(sourceRect.top, targetRect.top) - WIRE_CLEARANCE * BACKWARD_LOOP_CLEARANCE_MULTIPLIER;
    const belowY = Math.max(sourceRect.bottom, targetRect.bottom) + WIRE_CLEARANCE * BACKWARD_LOOP_CLEARANCE_MULTIPLIER;

    const distanceAbove = Math.abs(source.y - aboveY) + Math.abs(target.y - aboveY);
    const distanceBelow = Math.abs(source.y - belowY) + Math.abs(target.y - belowY);
    const detourY = distanceAbove <= distanceBelow ? aboveY : belowY;

    const exitOffset = Math.max(EXIT_STUB_MINIMUM, WIRE_CLEARANCE * BACKWARD_STUB_CLEARANCE_MULTIPLIER);
    const entryOffset = Math.max(EXIT_STUB_MINIMUM, WIRE_CLEARANCE * BACKWARD_STUB_CLEARANCE_MULTIPLIER);

    const exitStub: IPoint = { x: source.x + exitOffset, y: source.y };
    const entryStub: IPoint = { x: target.x - entryOffset, y: target.y };

    return [exitStub, { x: exitStub.x, y: detourY }, { x: entryStub.x, y: detourY }, entryStub];
}

// ---------------------------------------------------------------------------
// Obstacle avoidance for forward wires
// ---------------------------------------------------------------------------

function routeAroundObstacles(source: IPoint, target: IPoint, initialPoints: IPoint[], obstacles: Rect[]): IPoint[] {
    // Sort obstacles left-to-right so detour points are generated in wire order.
    const sorted = [...obstacles].sort((first, second) => first.left - second.left);
    const throughPoints: IPoint[] = [];

    let currentY = source.y;
    for (const obstacle of sorted) {
        // Decide whether to detour above or below this obstacle.
        const midY = (source.y + target.y) / 2;
        const obstacleCenterY = (obstacle.top + obstacle.bottom) / 2;
        const detourAbove = midY <= obstacleCenterY;
        const detourY = detourAbove
            ? obstacle.top - WIRE_CLEARANCE * DETOUR_CLEARANCE_MULTIPLIER
            : obstacle.bottom + WIRE_CLEARANCE * DETOUR_CLEARANCE_MULTIPLIER;

        throughPoints.push({ x: obstacle.left - WIRE_CLEARANCE, y: currentY });
        throughPoints.push({ x: obstacle.left - WIRE_CLEARANCE, y: detourY });
        throughPoints.push({ x: obstacle.right + WIRE_CLEARANCE, y: detourY });
        currentY = detourY;
    }

    // After the last obstacle, add a point to return toward the target's Y.
    if (throughPoints.length > 0) {
        const lastPoint = throughPoints[throughPoints.length - 1];
        if (lastPoint.y !== target.y) {
            throughPoints.push({ x: lastPoint.x, y: target.y });
        }
    }

    // If no detours were generated (shouldn't happen given the guard), fall back to initial points.
    return throughPoints.length > 0 ? throughPoints : initialPoints;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Finds obstacle rects (excluding source and target nodes) that lie between
 * two X coordinates and whose Y range overlaps with the curve's vertical span.
 */
function findObstaclesBetween(
    source: IPoint,
    target: IPoint,
    obstaclesById: Map<string, Rect>,
    sourceNodeId: string,
    targetNodeId: string
): Rect[] {
    const minX = Math.min(source.x, target.x);
    const maxX = Math.max(source.x, target.x);
    const minY = Math.min(source.y, target.y) - WIRE_CLEARANCE;
    const maxY = Math.max(source.y, target.y) + WIRE_CLEARANCE;

    const result: Rect[] = [];
    for (const [nodeId, rect] of obstaclesById) {
        if (nodeId === sourceNodeId || nodeId === targetNodeId) continue;
        if (rect.right < minX || rect.left > maxX) continue;
        if (rect.bottom < minY || rect.top > maxY) continue;
        result.push(rect);
    }
    return result;
}
