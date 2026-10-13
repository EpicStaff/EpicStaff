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
const LANE_SPACING = 10;

interface LaneInfo {
    index: number; // 0-based position among siblings
    count: number; // total siblings sharing the port
}

/**
 * Groups forward connections that share a source or target port and assigns
 * each a lane index. Wires are sorted by the Y of their other end so that
 * the topmost target gets lane 0, producing a fan that doesn't cross.
 */
function computeForwardLanes(connections: ConnectionModel[], nodesById: Map<string, NodeModel>): Map<string, LaneInfo> {
    const result = new Map<string, LaneInfo>();

    // Group connections by shared source port.
    const bySourcePort = new Map<string, { connectionId: string; targetY: number }[]>();
    // Group connections by shared target port.
    const byTargetPort = new Map<string, { connectionId: string; sourceY: number }[]>();

    for (const connection of connections) {
        if (connection.userAdjustedWaypoints) continue;
        const ends = resolveWireEnds(connection, nodesById);
        if (!ends) continue;
        const source = getPortPosition(ends.sourceNode, ends.sourcePort);
        const target = getPortPosition(ends.targetNode, ends.targetPort);
        if (target.x < source.x) continue; // skip backward/stacked

        const sourceKey = `${connection.sourceNodeId}@${connection.sourcePortId}`;
        const targetKey = `${connection.targetNodeId}@${connection.targetPortId}`;

        if (!bySourcePort.has(sourceKey)) bySourcePort.set(sourceKey, []);
        bySourcePort.get(sourceKey)!.push({ connectionId: connection.id, targetY: target.y });

        if (!byTargetPort.has(targetKey)) byTargetPort.set(targetKey, []);
        byTargetPort.get(targetKey)!.push({ connectionId: connection.id, sourceY: source.y });
    }

    // Assign lanes for connections sharing a source port (fan out).
    for (const siblings of bySourcePort.values()) {
        if (siblings.length < 2) continue;
        siblings.sort((a, b) => a.targetY - b.targetY);
        for (let i = 0; i < siblings.length; i++) {
            result.set(siblings[i].connectionId, { index: i, count: siblings.length });
        }
    }

    // Assign lanes for connections sharing a target port (fan in).
    // Only override if not already assigned from source grouping.
    for (const siblings of byTargetPort.values()) {
        if (siblings.length < 2) continue;
        siblings.sort((a, b) => a.sourceY - b.sourceY);
        for (let i = 0; i < siblings.length; i++) {
            if (!result.has(siblings[i].connectionId)) {
                result.set(siblings[i].connectionId, { index: i, count: siblings.length });
            }
        }
    }

    return result;
}

export function routeAllCurved(nodes: NodeModel[], connections: ConnectionModel[]): Map<string, IPoint[]> {
    const nodesById = new Map(nodes.map((node) => [node.id, node]));
    const obstaclesById = routingObstacles(nodes);
    const routes = new Map<string, IPoint[]>();

    // First pass: compute lane indices for forward connections that share a
    // source or target port. Wires from the same port get different Y offsets
    // so they don't draw on top of each other (like orthogonal nudging).
    const laneMap = computeForwardLanes(connections, nodesById);

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
        } else if (stacked && target.x < source.x) {
            throughPoints = routeStacked(source, target, sourceRect, targetRect);
        } else {
            const lane = laneMap.get(connection.id);
            throughPoints = routeForward(source, target, obstaclesById, connection, lane);
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
    connection: ConnectionModel,
    lane?: LaneInfo
): IPoint[] {
    const initialPoints = computeForwardControlPoints(source, target);

    // Separate overlapping wires by varying exit/entry stub lengths (X),
    // mirroring how the orthogonal router spaces risers at different X.
    // Lane 0 (topmost target) gets a shorter exit stub and longer entry stub;
    // higher lanes get progressively longer exit stubs and shorter entry stubs.
    if (lane && lane.count > 1) {
        const step = LANE_SPACING;
        const exitShift = (lane.index - (lane.count - 1) / 2) * step;
        const entryShift = -exitShift; // opposite: longer exit ↔ shorter entry
        initialPoints[0].x += exitShift;
        initialPoints[initialPoints.length - 1].x += entryShift;
    }

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

    // Each stub clears its own node. Push past the other node only when the
    // stub X is actually inside that node's rect (the descent would clip it).
    // Use raw rect bounds — MAX_TANGENT keeps the curve close to through-points.
    let exitStubX = Math.max(source.x + minStubOffset, sourceRect.right + swingClearance);
    if (exitStubX >= targetRect.left && exitStubX <= targetRect.right && targetRect.top < source.y) {
        exitStubX = Math.max(exitStubX, targetRect.right + swingClearance);
    }

    let entryStubX = Math.min(target.x - minStubOffset, targetRect.left - swingClearance);
    if (entryStubX >= sourceRect.left && entryStubX <= sourceRect.right && sourceRect.top < target.y) {
        entryStubX = Math.min(entryStubX, sourceRect.left - swingClearance);
    }

    // Push stubs past third-party obstacles in the descent path. Use tight
    // clearance (WIRE_CLEARANCE) and only consider obstacles above the port Y
    // (those actually in the vertical descent from loopY to the port).
    const exitStub = {
        x: pushStubPastObstacles(exitStubX, 'right', obstaclesById, connection, WIRE_CLEARANCE, source.y),
        y: source.y,
    };
    const entryStub = {
        x: pushStubPastObstacles(entryStubX, 'left', obstaclesById, connection, WIRE_CLEARANCE, target.y),
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

    // Same stub logic as routeBackward.
    let exitStubX = Math.max(source.x + minStubOffset, sourceRect.right + swingClearance);
    if (exitStubX >= targetRect.left && exitStubX <= targetRect.right && targetRect.top < source.y) {
        exitStubX = Math.max(exitStubX, targetRect.right + swingClearance);
    }

    let entryStubX = Math.min(target.x - minStubOffset, targetRect.left - swingClearance);
    if (entryStubX >= sourceRect.left && entryStubX <= sourceRect.right && sourceRect.top < target.y) {
        entryStubX = Math.min(entryStubX, sourceRect.left - swingClearance);
    }

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
    // For curved routing, keep the same 2-point S-curve shape from
    // computeForwardControlPoints but shift each point's Y so the curve
    // passes above or below every obstacle instead of through it.
    const clearance = WIRE_CLEARANCE * DETOUR_CLEARANCE_MULTIPLIER;
    const point1 = { ...initialPoints[0] };
    const point2 = { ...initialPoints[1] };

    for (const obstacle of obstacles) {
        const midY = (source.y + target.y) / 2;
        const obstacleCenterY = (obstacle.top + obstacle.bottom) / 2;
        const detourAbove = midY <= obstacleCenterY;

        const detourY = detourAbove ? obstacle.top - clearance : obstacle.bottom + clearance;

        // Push whichever through-point overlaps the obstacle's X range.
        if (point1.x >= obstacle.left - WIRE_CLEARANCE && point1.x <= obstacle.right + WIRE_CLEARANCE) {
            point1.y = detourAbove ? Math.min(point1.y, detourY) : Math.max(point1.y, detourY);
        }
        if (point2.x >= obstacle.left - WIRE_CLEARANCE && point2.x <= obstacle.right + WIRE_CLEARANCE) {
            point2.y = detourAbove ? Math.min(point2.y, detourY) : Math.max(point2.y, detourY);
        }

        // If neither through-point is in the obstacle's X range (obstacle is
        // between them), push both to ensure the curve clears it.
        if (point1.x < obstacle.left - WIRE_CLEARANCE && point2.x > obstacle.right + WIRE_CLEARANCE) {
            point1.y = detourAbove ? Math.min(point1.y, detourY) : Math.max(point1.y, detourY);
            point2.y = detourAbove ? Math.min(point2.y, detourY) : Math.max(point2.y, detourY);
        }
    }

    return [point1, point2];
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
    clearance: number,
    portY: number
): number {
    let result = stubX;
    for (const [nodeId, rect] of obstaclesById) {
        if (nodeId === connection.sourceNodeId || nodeId === connection.targetNodeId) continue;
        // Skip obstacles whose top is at or below the port — they are not in the
        // vertical descent path from loopY down to the port.
        if (rect.top >= portY) continue;
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
