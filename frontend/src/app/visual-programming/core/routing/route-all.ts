import { IPoint } from '@foblex/2d';

import { getPortPosition } from '../geometry/port-position';
import { isStacked } from '../geometry/wire-direction';
import { ConnectionModel } from '../models/connection.model';
import { NodeModel } from '../models/node.model';
import { ViewPort } from '../models/port.model';
import { removeJogs } from './jog-cleanup';
import { nudgePaths, RoutedPath } from './nudging';
import { Rect, routingObstacles, WIRE_CLEARANCE } from './obstacles';
import { fallbackRoutePoints } from './orthogonal-route-shapes';
import { findRoute, RouteOptions, SegmentIndex } from './path-search';
import { buildRoutingGrid } from './routing-grid';

/**
 * Routes every drawable connection: one routing grid per run, A* per wire in order of
 * stub-to-stub Manhattan distance (then id), every routed wire occupying its segments for the
 * next, then nudging into lanes and removing the kinks nudging leaves. Pure and deterministic, whatever the order of the inputs.
 *
 * The result maps connection id → interior points, the two port points left out (what
 * `ConnectionModel.waypoints` stores); a straight wire maps to `[]`. Left out of the result:
 * connections with `userAdjustedWaypoints` (they still occupy their corridor), connections on
 * top/bottom ports, and stale ones (a node or port missing).
 */

const STUB = 20;
// Stacked nodes at least this far apart (unpadded boxes) get the return leg in the gap, the
// one wire that fits there with WIRE_CLEARANCE on either side.
const STACKED_GAP_THRESHOLD = 2 * WIRE_CLEARANCE;

export interface WireEnds {
    sourceNode: NodeModel;
    targetNode: NodeModel;
    sourcePort: ViewPort;
    targetPort: ViewPort;
}

interface PlannedWire {
    connection: ConnectionModel;
    source: IPoint; // port points
    target: IPoint;
    start: IPoint; // stub ends
    goal: IPoint;
    options: RouteOptions;
}

// Connection ids already reported as unroutable: the warning is logged once per id.
const warnedConnectionIds = new Set<string>();

/**
 * The nodes and ports a connection joins, or null when it can't be drawn: a node or port is
 * missing (stale), or a port is top/bottom (only TOOL has those; the router leaves them alone).
 */
export function resolveWireEnds(connection: ConnectionModel, nodesById: Map<string, NodeModel>): WireEnds | null {
    const sourceNode = nodesById.get(connection.sourceNodeId);
    const targetNode = nodesById.get(connection.targetNodeId);
    const sourcePort = sourceNode?.ports?.find((candidate) => candidate.id === connection.sourcePortId);
    const targetPort = targetNode?.ports?.find((candidate) => candidate.id === connection.targetPortId);
    if (!sourceNode || !targetNode || !sourcePort || !targetPort) return null;
    const isVertical = (port: ViewPort): boolean => port.position === 'top' || port.position === 'bottom';
    if (isVertical(sourcePort) || isVertical(targetPort)) return null;
    return { sourceNode, targetNode, sourcePort, targetPort };
}

export function routeAll(nodes: NodeModel[], connections: ConnectionModel[]): Map<string, IPoint[]> {
    const nodesById = new Map(nodes.map((node) => [node.id, node]));
    const obstaclesById = routingObstacles(nodes);
    const obstacles = [...obstaclesById.values()];
    const planned: PlannedWire[] = [];
    const frozen: RoutedPath[] = [];
    for (const connection of connections) {
        const ends = resolveWireEnds(connection, nodesById);
        if (!ends) continue;
        const source = getPortPosition(ends.sourceNode, ends.sourcePort);
        const target = getPortPosition(ends.targetNode, ends.targetPort);
        if (connection.userAdjustedWaypoints) {
            frozen.push(routedPath(connection, [source, ...(connection.waypoints ?? []), target]));
            continue;
        }
        planned.push({
            connection,
            source,
            target,
            start: { x: source.x + STUB, y: source.y },
            goal: { x: target.x - STUB, y: target.y },
            options: routeOptions(ends, source, target, obstaclesById),
        });
    }
    planned.sort(
        (first, second) =>
            stubDistance(first) - stubDistance(second) || compareIds(first.connection.id, second.connection.id)
    );

    // Frozen wires' corners become grid lines too, so every occupied segment lies on the grid.
    const frozenPoints = frozen.flatMap((path) => path.points);
    const grid = buildRoutingGrid(
        obstacles,
        [...planned.flatMap((wire) => [wire.start.x, wire.goal.x]), ...frozenPoints.map((point) => point.x)],
        [...planned.flatMap((wire) => [wire.start.y, wire.goal.y]), ...frozenPoints.map((point) => point.y)]
    );
    const occupied = new SegmentIndex();
    frozen.forEach((path) => occupied.add(path));
    // Every stub is known before anything is routed: reserving them keeps a wire routed early off
    // the stub a later one needs (a stub never moves, so an overlap there is for good).
    for (const wire of planned) {
        const ports = routedPath(wire.connection, [wire.source, wire.target]);
        occupied.add({ ...ports, points: [wire.source, wire.start] });
        occupied.add({ ...ports, points: [wire.goal, wire.target] });
    }

    const routed = planned.map((wire) => {
        const { connection } = wire;
        const ports = routedPath(connection, [wire.source, wire.target]);
        const ownPorts = { source: ports.sourcePortKey, target: ports.targetPortKey };
        // A stacked pair's wire returns through the gap; without room there it goes around. A
        // return wire goes over the top; unconstrained only when no such route exists.
        const constrained = wire.options.rows !== undefined || wire.options.legsAbove !== undefined;
        const found =
            (constrained ? findRoute(grid, wire.start, wire.goal, occupied, ownPorts, wire.options) : null) ??
            findRoute(grid, wire.start, wire.goal, occupied, ownPorts);
        const path = routedPath(
            connection,
            removeCollinear(found ? [wire.source, ...found, wire.target] : fallbackFor(wire))
        );
        // The stubs are in already; the route between them (or the whole fallback) goes in now.
        occupied.add(found ? { ...path, points: found } : path);
        return path;
    });

    const routes = new Map<string, IPoint[]>();
    for (const path of removeJogs(nudgePaths(routed, obstacles, frozen), obstacles, frozen)) {
        routes.set(path.id, path.points.slice(1, -1));
    }
    return routes;
}

/**
 * A wire whose target input is left of the source output:
 * - stacked (the boxes overlap in x), with at least 20 px between the node boxes: the search
 *   may only use rows from the upper node's top to the lower node's bottom. The westward leg then
 *   can only run in the gap between them, and no leg goes over or under the stack;
 * - a return wire (the boxes apart in x): every leg between the two
 *   stubs' columns runs at or above both padded tops. Over the top of both ends, never under;
 *   not over every node, so a loop into a table stays just above that table.
 */
function routeOptions(ends: WireEnds, source: IPoint, target: IPoint, obstaclesById: Map<string, Rect>): RouteOptions {
    const sourceBox = obstaclesById.get(ends.sourceNode.id);
    const targetBox = obstaclesById.get(ends.targetNode.id);
    if (!sourceBox || !targetBox || ends.sourceNode === ends.targetNode || target.x >= source.x) return {};
    if (!isStacked(sourceBox, targetBox)) return { legsAbove: Math.min(sourceBox.top, targetBox.top) };
    const [upper, lower] =
        ends.sourceNode.position.y <= ends.targetNode.position.y ? [sourceBox, targetBox] : [targetBox, sourceBox];
    // The obstacles pad every node by WIRE_CLEARANCE above and below.
    const top = upper.top + WIRE_CLEARANCE;
    const bottom = lower.bottom - WIRE_CLEARANCE;
    const gap = lower.top - upper.bottom + 2 * WIRE_CLEARANCE;
    return gap >= STACKED_GAP_THRESHOLD ? { rows: { top, bottom } } : {};
}

function fallbackFor(wire: PlannedWire): IPoint[] {
    const { id } = wire.connection;
    if (!warnedConnectionIds.has(id)) {
        warnedConnectionIds.add(id);
        console.warn(`routeAll: no route for connection ${id}; drawing the fallback shape`);
    }
    return fallbackRoutePoints(wire.source, wire.target);
}

// Trunks are keyed by where a port is drawn, not by its id: wires leaving one point are one trunk
// to the eye, even from two port ids at the same spot.
function routedPath(connection: ConnectionModel, points: IPoint[]): RoutedPath {
    const source = points[0];
    const target = points[points.length - 1];
    return {
        id: connection.id,
        sourcePortKey: `${connection.sourceNodeId}@${source.x},${source.y}`,
        targetPortKey: `${connection.targetNodeId}@${target.x},${target.y}`,
        points,
    };
}

function stubDistance(wire: PlannedWire): number {
    return Math.abs(wire.goal.x - wire.start.x) + Math.abs(wire.goal.y - wire.start.y);
}

// Drops points lying on the straight line between their neighbours (the stub ends of a straight run).
function removeCollinear(points: IPoint[]): IPoint[] {
    const result: IPoint[] = [];
    for (const point of points) {
        const previous = result[result.length - 1];
        if (previous && previous.x === point.x && previous.y === point.y) continue;
        if (result.length >= 2) {
            const beforePrevious = result[result.length - 2];
            const vertical = beforePrevious.x === previous.x && previous.x === point.x;
            const horizontal = beforePrevious.y === previous.y && previous.y === point.y;
            if (vertical || horizontal) result.pop();
        }
        result.push(point);
    }
    return result;
}

function compareIds(first: string, second: string): number {
    return first < second ? -1 : first > second ? 1 : 0;
}
