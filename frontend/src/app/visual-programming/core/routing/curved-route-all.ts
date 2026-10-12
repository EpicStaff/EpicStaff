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
    const minStubOffset = Math.max(EXIT_STUB_MINIMUM, WIRE_CLEARANCE * BACKWARD_STUB_CLEARANCE_MULTIPLIER);
    const swingClearance = WIRE_CLEARANCE * DETOUR_CLEARANCE_MULTIPLIER;

    // Ensure stubs extend past BOTH node bodies so the Catmull-Rom curve
    // doesn't swing through a node at the vertical rise/drop turns.
    const exitStubX = Math.max(
        source.x + minStubOffset,
        sourceRect.right + swingClearance,
        targetRect.right + swingClearance
    );
    const entryStubX = Math.min(
        target.x - minStubOffset,
        sourceRect.left - swingClearance,
        targetRect.left - swingClearance
    );

    // Also push stubs past any other obstacle node in the vertical column
    const exitStub = {
        x: pushStubPastObstacles(exitStubX, 'right', obstaclesById, connection, swingClearance),
        y: source.y,
    };
    const entryStub = {
        x: pushStubPastObstacles(entryStubX, 'left', obstaclesById, connection, swingClearance),
        y: target.y,
    };

    // Always loop above — matches orthogonal router behaviour.
    const loopClearance = WIRE_CLEARANCE * BACKWARD_LOOP_CLEARANCE_MULTIPLIER;
    let loopY = Math.min(sourceRect.top, targetRect.top) - loopClearance;

    const loopLeft = Math.min(entryStub.x, exitStub.x);
    const loopRight = Math.max(entryStub.x, exitStub.x);
    const portBottom = Math.max(source.y, target.y);

    // Push loopY above any obstacle that actually overlaps the route's
    // vertical range [loopY, portBottom].
    for (const [nodeId, rect] of obstaclesById) {
        if (nodeId === connection.sourceNodeId || nodeId === connection.targetNodeId) continue;
        if (rect.right < loopLeft || rect.left > loopRight) continue;

        const blocksRoute = rect.bottom > loopY - WIRE_CLEARANCE && rect.top < portBottom + WIRE_CLEARANCE;
        if (blocksRoute && rect.top < loopY + WIRE_CLEARANCE) {
            loopY = rect.top - loopClearance;
        }
    }

    // Offset stub Y slightly toward loopY so the Catmull-Rom tangent at the
    // stub already points toward the loop, preventing the "knee" dip that
    // occurs when the stub sits at source/target Y and the next point is
    // far above.
    const STUB_Y_BLEND = 0.15;
    const exitStubY = source.y + (loopY - source.y) * STUB_Y_BLEND;
    const entryStubY = target.y + (loopY - target.y) * STUB_Y_BLEND;

    return [
        { x: exitStub.x, y: exitStubY },
        { x: exitStub.x, y: loopY },
        { x: entryStub.x, y: loopY },
        { x: entryStub.x, y: entryStubY },
    ];
}

// ---------------------------------------------------------------------------
// Stacked nodes: overlapping in X
// ---------------------------------------------------------------------------

function routeStacked(source: IPoint, target: IPoint, sourceRect: Rect, targetRect: Rect): IPoint[] {
    const [upperRect, lowerRect] =
        sourceRect.top <= targetRect.top ? [sourceRect, targetRect] : [targetRect, sourceRect];
    const gapBetween = lowerRect.top - upperRect.bottom;
    const swingClearance = WIRE_CLEARANCE * DETOUR_CLEARANCE_MULTIPLIER;
    const minStubOffset = Math.max(EXIT_STUB_MINIMUM, WIRE_CLEARANCE * BACKWARD_STUB_CLEARANCE_MULTIPLIER);

    // Ensure stubs extend past both node bodies
    const exitStubX = Math.max(
        source.x + minStubOffset,
        sourceRect.right + swingClearance,
        targetRect.right + swingClearance
    );
    const entryStubX = Math.min(
        target.x - minStubOffset,
        sourceRect.left - swingClearance,
        targetRect.left - swingClearance
    );

    const STUB_Y_BLEND = 0.15;

    if (gapBetween >= 2 * WIRE_CLEARANCE) {
        // Route through the gap between stacked nodes.
        const gapY = upperRect.bottom + gapBetween / 2;
        const exitStubY = source.y + (gapY - source.y) * STUB_Y_BLEND;
        const entryStubY = target.y + (gapY - target.y) * STUB_Y_BLEND;
        return [
            { x: exitStubX, y: exitStubY },
            { x: exitStubX, y: gapY },
            { x: entryStubX, y: gapY },
            { x: entryStubX, y: entryStubY },
        ];
    }

    // No gap — route around above or below, whichever is shorter.
    const aboveY = Math.min(sourceRect.top, targetRect.top) - WIRE_CLEARANCE * BACKWARD_LOOP_CLEARANCE_MULTIPLIER;
    const belowY = Math.max(sourceRect.bottom, targetRect.bottom) + WIRE_CLEARANCE * BACKWARD_LOOP_CLEARANCE_MULTIPLIER;

    const distanceAbove = Math.abs(source.y - aboveY) + Math.abs(target.y - aboveY);
    const distanceBelow = Math.abs(source.y - belowY) + Math.abs(target.y - belowY);
    const detourY = distanceAbove <= distanceBelow ? aboveY : belowY;

    const exitStubY = source.y + (detourY - source.y) * STUB_Y_BLEND;
    const entryStubY = target.y + (detourY - target.y) * STUB_Y_BLEND;

    return [
        { x: exitStubX, y: exitStubY },
        { x: exitStubX, y: detourY },
        { x: entryStubX, y: detourY },
        { x: entryStubX, y: entryStubY },
    ];
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
 * Pushes a stub X coordinate past any obstacle node whose horizontal span
 * includes the current stub position. For 'right' direction, pushes further
 * right; for 'left', pushes further left.
 */
function pushStubPastObstacles(
    stubX: number,
    direction: 'left' | 'right',
    obstaclesById: Map<string, Rect>,
    connection: ConnectionModel,
    clearance: number
): number {
    let result = stubX;
    for (const [nodeId, rect] of obstaclesById) {
        if (nodeId === connection.sourceNodeId || nodeId === connection.targetNodeId) continue;
        if (direction === 'right' && result >= rect.left - clearance && result <= rect.right + clearance) {
            result = rect.right + clearance;
        } else if (direction === 'left' && result >= rect.left - clearance && result <= rect.right + clearance) {
            result = rect.left - clearance;
        }
    }
    return result;
}

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
