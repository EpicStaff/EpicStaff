import { IPoint } from '@foblex/2d';
import { NodeType } from '@shared/models';

import { getPortPosition } from '../../geometry/port-position';
import { isBackwardWire, isStacked } from '../../geometry/wire-direction';
import { resolveRowIndex } from '../../helpers/cdt-row-snap.util';
import { getClassificationTableVisualHeight, getDecisionTableVisualHeight } from '../../helpers/node-size.util';
import { ConnectionModel } from '../../models/connection.model';
import { ClassificationDecisionTableNodeModel, DecisionTableNodeModel, NodeModel } from '../../models/node.model';
import { obstacleRect, WIRE_CLEARANCE } from '../../routing/obstacles';
import { pathSelfIntersects } from '../../routing/path-self-intersects';
import { resolveWireEnds } from '../../routing/route-all';

/**
 * Layout and routing quality, measured on geometry alone. Pure and deterministic. The rule codes
 * below are used throughout this file.
 *
 * Hard rules: 0 violations on arranged and routed output, or the quality specs fail.
 * - H1 no node overlap: nodes whose x-ranges overlap keep a vertical gap of at least 20 px, except
 *   siblings that are each straight on consecutive rows of one table, which may touch.
 * - H2 wire never crosses a node: no segment enters a node's padded box; a wire's own end nodes
 *   are exempt only for its first and last segment (the stubs).
 * - H3 no collinear overlap: no two wires run on top of each other for more than 1 px, unless
 *   they share a source or a target port (a trunk).
 * - H4 no self-intersection: no wire crosses itself.
 * - H5 stub of at least 20 px: the first segment leaves the source port to the right and the last
 *   enters the target port from the left, each at least 20 px long.
 * - H6 deterministic: the same input gives the same output, even with nodes and connections
 *   shuffled.
 * - H7 idempotent arrange: arranging its own output moves no node.
 * - H8 on the 20-px grid: every node top is on the grid, unless leaving it makes an input wire
 *   straight or puts the input port on the median of its feeding ports.
 * - H9 return through the stacked gap: when source and target are stacked, the target's entry
 *   left of the source's exit, with at least 20 px between their unpadded boxes and no other node
 *   there, the return leg runs inside that gap and never above or below the pair.
 * - H10 no kinks: every interior segment (between two bends) is at least 10 px long.
 *
 * Soft metrics: compared with the regression limits in the quality specs.
 * - S1 crossings: proper crossings between segments of different wires.
 * - S2 bends: interior points after collinear simplification.
 * - S3 straight wires: wires with exactly two points.
 * - S4 area: the bounding box area of the nodes.
 * - S5 clearance: at least 10 px between parallel lanes where the channel allows, and between a
 *   wire and a node above or below it. The obstacle padding and nudging enforce it.
 *
 * `measure` counts H1–H5, H8–H10 and S1–S4; the layout and router specs check H6 and H7.
 */

export interface RoutedWire {
    id: string;
    sourcePortKey: string;
    targetPortKey: string;
    sourceNodeId: string;
    targetNodeId: string;
    points: IPoint[]; // full points, port to port
}

export interface QualityReport {
    nodeOverlaps: number; // H1: pairs of real-node boxes that intersect, or in one column closer than 20 (straight row siblings may touch)
    wireThroughNode: number; // H2: wire-node pairs where any segment except the first/last stub enters the router's obstacle box (obstacleRect) of a node
    collinearOverlaps: number; // H3: wire pairs with a collinear overlap > 1px that share neither source nor target port
    selfIntersections: number; // H4: via pathSelfIntersects
    badStubs: number; // H5: first segment not → by ≥ 20, or last segment not → by ≥ 20 (each end counts)
    offGrid: number; // H8: node tops with y % 20 !== 0 whose input wire is not straight
    stackedGapViolations: number; // H9
    shortSegments: number; // H10: interior segments (between two bends; stubs are H5's) shorter than 10 px
    crossings: number; // S1: proper perpendicular crossings between segments of different wires
    bends: number; // S2: total interior points after collinear simplification
    straightAdjacent: number; // S3: wires with exactly 2 points (straight)
    wires: number;
    area: number; // S4: bounding box area of the nodes
}

interface Box {
    left: number;
    top: number;
    right: number;
    bottom: number;
}

const STUB = 20;
// H1 and H9: the gap one wire fits in, WIRE_CLEARANCE above and below it.
const SIBLING_GAP = 2 * WIRE_CLEARANCE;
const GRID = 20;
const STACKED_GAP_THRESHOLD = 2 * WIRE_CLEARANCE;
// H10: an interior segment shorter than this reads as a kink, not a lane.
const MIN_INTERIOR_SEGMENT = 10;
const MIN_COLLINEAR_OVERLAP = 1;
// Sub-pixel tolerance: two lines closer than this are drawn on the same pixel row.
const EPSILON = 0.5;

/**
 * Wires for `measure`. `routes` holds either full points or interior waypoints only (what
 * `ConnectionModel.waypoints` stores); interior routes get the port points from getPortPosition.
 * Connections without a route, stale ones and top/bottom-port ones are left out.
 */
export function wiresFromRoutes(
    nodes: NodeModel[],
    connections: ConnectionModel[],
    routes: Map<string, IPoint[]>,
    routesAreInterior: boolean
): RoutedWire[] {
    const nodesById = new Map(nodes.map((node) => [node.id, node]));
    const wires: RoutedWire[] = [];
    for (const connection of connections) {
        const route = routes.get(connection.id);
        const ends = resolveWireEnds(connection, nodesById);
        if (!route || !ends) continue;
        const points = routesAreInterior
            ? [
                  getPortPosition(ends.sourceNode, ends.sourcePort),
                  ...route,
                  getPortPosition(ends.targetNode, ends.targetPort),
              ]
            : route;
        wires.push({
            id: connection.id,
            sourcePortKey: connection.sourcePortId,
            targetPortKey: connection.targetPortId,
            sourceNodeId: connection.sourceNodeId,
            targetNodeId: connection.targetNodeId,
            points: simplify(points),
        });
    }
    return wires;
}

/** Whether a routed wire is backward, by the classification the canvas and the router use. */
export function isBackwardRoutedWire(nodesById: Map<string, NodeModel>, wire: RoutedWire): boolean {
    const source = nodesById.get(wire.sourceNodeId);
    const target = nodesById.get(wire.targetNodeId);
    if (!source || !target || wire.points.length < 2) return false;
    return isBackwardWire(
        wire.points[0],
        wire.points[wire.points.length - 1],
        obstacleRect(source),
        obstacleRect(target)
    );
}

export function measure(nodes: NodeModel[], wires: RoutedWire[]): QualityReport {
    const realNodes = nodes.filter((node) => node.type !== NodeType.NOTE);
    const nodesById = new Map(realNodes.map((node) => [node.id, node]));
    const simplified = wires.map((wire) => ({ ...wire, points: simplify(wire.points) }));

    return {
        nodeOverlaps: countNodeOverlaps(realNodes, nodesById, simplified),
        wireThroughNode: countWiresThroughNodes(realNodes, simplified),
        collinearOverlaps: countCollinearOverlaps(simplified),
        selfIntersections: simplified.filter((wire) => pathSelfIntersects(wire.points)).length,
        badStubs: countBadStubs(simplified),
        offGrid: countOffGrid(realNodes, simplified),
        stackedGapViolations: countStackedGapViolations(nodesById, simplified),
        shortSegments: countShortSegments(simplified),
        crossings: countCrossings(simplified),
        bends: simplified.reduce((total, wire) => total + Math.max(wire.points.length - 2, 0), 0),
        straightAdjacent: simplified.filter((wire) => wire.points.length === 2).length,
        wires: simplified.length,
        area: boundingArea(realNodes),
    };
}

// Drops repeated points and interior points that lie on the straight line between their neighbours.
// A point where the wire doubles back on itself is kept: that reversal is real geometry.
function simplify(points: IPoint[]): IPoint[] {
    const deduplicated = points.filter((point, index) => index === 0 || !samePoint(point, points[index - 1]));
    const result: IPoint[] = [];
    for (const point of deduplicated) {
        while (result.length >= 2 && isBetweenOnLine(result[result.length - 2], result[result.length - 1], point)) {
            result.pop();
        }
        result.push(point);
    }
    return result;
}

function samePoint(first: IPoint, second: IPoint): boolean {
    return Math.abs(first.x - second.x) < EPSILON && Math.abs(first.y - second.y) < EPSILON;
}

function isBetweenOnLine(start: IPoint, middle: IPoint, end: IPoint): boolean {
    const cross = (middle.x - start.x) * (end.y - start.y) - (middle.y - start.y) * (end.x - start.x);
    const length = Math.hypot(end.x - start.x, end.y - start.y);
    if (length === 0 || Math.abs(cross) / length >= EPSILON) return false;
    const dot = (middle.x - start.x) * (end.x - middle.x) + (middle.y - start.y) * (end.y - middle.y);
    return dot >= 0;
}

function nodeHeight(node: NodeModel): number {
    if (node.type === NodeType.TABLE) {
        return getDecisionTableVisualHeight((node as DecisionTableNodeModel).data.table?.condition_groups ?? []);
    }
    if (node.type === NodeType.CLASSIFICATION_TABLE) {
        const conditionGroups = (node as ClassificationDecisionTableNodeModel).data.table?.condition_groups ?? [];
        return getClassificationTableVisualHeight(conditionGroups);
    }
    return node.size.height;
}

// The rendered box: a table's height is its visual height, which wins over `size.height`.
function realBox(node: NodeModel): Box {
    const { x, y } = node.position;
    return { left: x, top: y, right: x + node.size.width, bottom: y + nodeHeight(node) };
}

function rangesOverlap(firstStart: number, firstEnd: number, secondStart: number, secondEnd: number): boolean {
    return firstStart < secondEnd && secondStart < firstEnd;
}

interface RowSlot {
    tableId: string;
    rowIndex: number;
}

// The table rows each node sits straight on: an incoming wire from a table row whose port y
// equals the node's input port y.
function straightRowSlots(nodesById: Map<string, NodeModel>, wires: RoutedWire[]): Map<string, RowSlot[]> {
    const slots = new Map<string, RowSlot[]>();
    for (const wire of wires) {
        const table = nodesById.get(wire.sourceNodeId);
        if (!table || (table.type !== NodeType.TABLE && table.type !== NodeType.CLASSIFICATION_TABLE)) continue;
        if (Math.abs(wire.points[0].y - wire.points[wire.points.length - 1].y) >= EPSILON) continue;
        const role = table.ports?.find((candidate) => candidate.id === wire.sourcePortKey)?.role;
        const rowIndex = role ? resolveRowIndex(table as DecisionTableNodeModel, role) : null;
        if (rowIndex === null) continue;
        slots.set(wire.targetNodeId, [...(slots.get(wire.targetNodeId) ?? []), { tableId: table.id, rowIndex }]);
    }
    return slots;
}

// "Same column" is read as overlapping x-ranges, which covers the same x and also right-aligned
// layers, where nodes of different widths share a right edge but not a left one. Siblings that
// are each straight on consecutive rows of one table may touch: straight rows win (H1).
function countNodeOverlaps(nodes: NodeModel[], nodesById: Map<string, NodeModel>, wires: RoutedWire[]): number {
    const boxes = nodes.map(realBox);
    const slots = straightRowSlots(nodesById, wires);
    const areRowSiblings = (firstId: string, secondId: string): boolean =>
        (slots.get(firstId) ?? []).some((first) =>
            (slots.get(secondId) ?? []).some(
                (second) => first.tableId === second.tableId && Math.abs(first.rowIndex - second.rowIndex) === 1
            )
        );
    let count = 0;
    for (let first = 0; first < boxes.length; first++) {
        for (let second = first + 1; second < boxes.length; second++) {
            const a = boxes[first];
            const b = boxes[second];
            if (!rangesOverlap(a.left, a.right, b.left, b.right)) continue;
            const verticalGap = Math.max(b.top - a.bottom, a.top - b.bottom);
            const minimumGap = areRowSiblings(nodes[first].id, nodes[second].id) ? 0 : SIBLING_GAP;
            if (verticalGap < minimumGap) count++;
        }
    }
    return count;
}

// Liang–Barsky clip of the segment to the closed box; it enters when the clipped part has length
// and its midpoint is strictly inside. Running along an edge or touching a corner does not count.
function segmentEntersBox(start: IPoint, end: IPoint, box: Box): boolean {
    const deltaX = end.x - start.x;
    const deltaY = end.y - start.y;
    let enter = 0;
    let exit = 1;
    const clips: [number, number][] = [
        [-deltaX, start.x - box.left],
        [deltaX, box.right - start.x],
        [-deltaY, start.y - box.top],
        [deltaY, box.bottom - start.y],
    ];
    for (const [direction, distance] of clips) {
        if (direction === 0) {
            if (distance < 0) return false;
            continue;
        }
        const ratio = distance / direction;
        if (direction < 0) enter = Math.max(enter, ratio);
        else exit = Math.min(exit, ratio);
        if (enter > exit) return false;
    }
    if (exit - enter <= 0) return false;
    const middle = (enter + exit) / 2;
    const x = start.x + deltaX * middle;
    const y = start.y + deltaY * middle;
    return x > box.left && x < box.right && y > box.top && y < box.bottom;
}

function countWiresThroughNodes(nodes: NodeModel[], wires: RoutedWire[]): number {
    const boxes = nodes.map((node) => ({ id: node.id, box: obstacleRect(node) }));
    let count = 0;
    for (const wire of wires) {
        const lastSegment = wire.points.length - 2;
        for (const { id, box } of boxes) {
            const isOwnEnd = id === wire.sourceNodeId || id === wire.targetNodeId;
            for (let segment = 0; segment <= lastSegment; segment++) {
                if (isOwnEnd && (segment === 0 || segment === lastSegment)) continue;
                if (segmentEntersBox(wire.points[segment], wire.points[segment + 1], box)) {
                    count++;
                    break;
                }
            }
        }
    }
    return count;
}

interface AxisSegment {
    horizontal: boolean;
    line: number; // y of a horizontal segment, x of a vertical one
    from: number;
    to: number;
}

function axisSegments(points: IPoint[]): AxisSegment[] {
    const segments: AxisSegment[] = [];
    for (let index = 0; index < points.length - 1; index++) {
        const start = points[index];
        const end = points[index + 1];
        if (Math.abs(start.y - end.y) < EPSILON) {
            segments.push({
                horizontal: true,
                line: start.y,
                from: Math.min(start.x, end.x),
                to: Math.max(start.x, end.x),
            });
        } else if (Math.abs(start.x - end.x) < EPSILON) {
            segments.push({
                horizontal: false,
                line: start.x,
                from: Math.min(start.y, end.y),
                to: Math.max(start.y, end.y),
            });
        }
    }
    return segments;
}

// Wires leaving the same source port or entering the same target port form a trunk (H3 exempt).
// Two port keys drawn at one point are one port to the eye (the random graphs give plain nodes two
// right ports, `out0` and `out1`, at the same spot; no real node type has that), so they count too.
function sharesTrunk(a: RoutedWire, b: RoutedWire): boolean {
    const sameSource = a.sourcePortKey === b.sourcePortKey || samePoint(a.points[0], b.points[0]);
    const sameTarget =
        a.targetPortKey === b.targetPortKey || samePoint(a.points[a.points.length - 1], b.points[b.points.length - 1]);
    return sameSource || sameTarget;
}

function countCollinearOverlaps(wires: RoutedWire[]): number {
    const segmentsByWire = wires.map((wire) => axisSegments(wire.points));
    let count = 0;
    for (let first = 0; first < wires.length; first++) {
        for (let second = first + 1; second < wires.length; second++) {
            const a = wires[first];
            const b = wires[second];
            if (sharesTrunk(a, b)) continue;
            const overlapping = segmentsByWire[first].some((segmentA) =>
                segmentsByWire[second].some(
                    (segmentB) =>
                        segmentA.horizontal === segmentB.horizontal &&
                        Math.abs(segmentA.line - segmentB.line) < EPSILON &&
                        Math.min(segmentA.to, segmentB.to) - Math.max(segmentA.from, segmentB.from) >
                            MIN_COLLINEAR_OVERLAP
                )
            );
            if (overlapping) count++;
        }
    }
    return count;
}

// Level within the tolerance simplify() uses, so a wire simplify() calls straight has level stubs.
function isGoodStub(start: IPoint, end: IPoint): boolean {
    return Math.abs(end.y - start.y) <= EPSILON && end.x - start.x >= STUB - EPSILON;
}

function countBadStubs(wires: RoutedWire[]): number {
    let count = 0;
    for (const { points } of wires) {
        if (points.length < 2) continue;
        if (!isGoodStub(points[0], points[1])) count++;
        if (!isGoodStub(points[points.length - 2], points[points.length - 1])) count++;
    }
    return count;
}

// H10: the segments between the first and the last (the stubs), shorter than 10 px within the
// sub-pixel tolerance. Exempt: the lone segment between two stubs whose ports are less than 10 px
// apart vertically; its length is that offset, and nothing but a detour could lengthen it.
function countShortSegments(wires: RoutedWire[]): number {
    let count = 0;
    for (const { points } of wires) {
        const loneBetweenStubs = points.length === 4;
        if (loneBetweenStubs && Math.abs(points[3].y - points[0].y) < MIN_INTERIOR_SEGMENT) continue;
        for (let index = 1; index < points.length - 2; index++) {
            const length = Math.hypot(points[index + 1].x - points[index].x, points[index + 1].y - points[index].y);
            if (length < MIN_INTERIOR_SEGMENT - EPSILON) count++;
        }
    }
    return count;
}

function median(values: number[]): number {
    const sorted = [...values].sort((a, b) => a - b);
    const middle = Math.floor(sorted.length / 2);
    return sorted.length % 2 === 1 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

// Off the 20-px grid is allowed only for alignment: a straight input wire, or an input port on
// the median of its feeding ports (a node centred between two rows).
function countOffGrid(nodes: NodeModel[], wires: RoutedWire[]): number {
    let count = 0;
    for (const node of nodes) {
        const remainder = ((node.position.y % GRID) + GRID) % GRID;
        if (remainder < EPSILON || GRID - remainder < EPSILON) continue;
        const incoming = wires.filter((wire) => wire.targetNodeId === node.id && wire.points.length >= 2);
        const hasStraightInput = incoming.some((wire) => wire.points.length === 2);
        const inputY = incoming.length > 0 ? incoming[0].points[incoming[0].points.length - 1].y : null;
        const onFeedingMedian =
            inputY !== null && Math.abs(inputY - median(incoming.map((wire) => wire.points[0].y))) < EPSILON;
        if (!hasStraightInput && !onFeedingMedian) count++;
    }
    return count;
}

/**
 * H9: source and target stacked (padded boxes overlap in x, the target's entry left of the
 * source's exit) with a vertical gap ≥ 20 between the unpadded node boxes, and no other node in
 * that gap. The wire needs a horizontal leg strictly inside that gap and no horizontal leg above
 * the upper node or below the lower one.
 */
function countStackedGapViolations(nodesById: Map<string, NodeModel>, wires: RoutedWire[]): number {
    let count = 0;
    for (const wire of wires) {
        const stack = stackedGapBoxes(nodesById, wire);
        if (!stack) continue;
        const { upper, lower } = stack;
        const horizontals = axisSegments(wire.points).filter((segment) => segment.horizontal);
        const hasLegInGap = horizontals.some((segment) => segment.line > upper.bottom && segment.line < lower.top);
        const leavesTheStack = horizontals.some((segment) => segment.line < upper.top || segment.line > lower.bottom);
        if (!hasLegInGap || leavesTheStack) count++;
    }
    return count;
}

/** How many wires H9 applies to: the corpus must contain some, or H9 = 0 proves nothing. */
export function countStackedGapCases(nodes: NodeModel[], wires: RoutedWire[]): number {
    const nodesById = new Map(nodes.map((node) => [node.id, node]));
    return wires.filter((wire) => stackedGapBoxes(nodesById, wire) !== null).length;
}

// The unpadded boxes of an H9 case, upper first; null when H9 doesn't apply to the wire.
function stackedGapBoxes(nodesById: Map<string, NodeModel>, wire: RoutedWire): { upper: Box; lower: Box } | null {
    const source = nodesById.get(wire.sourceNodeId);
    const target = nodesById.get(wire.targetNodeId);
    if (!source || !target || source === target || wire.points.length < 2) return null;
    const sourceBox = obstacleRect(source);
    const targetBox = obstacleRect(target);
    if (!isStacked(sourceBox, targetBox)) return null;
    if (wire.points[wire.points.length - 1].x >= wire.points[0].x) return null;
    const [upper, lower] =
        source.position.y <= target.position.y ? [source, target].map(realBox) : [target, source].map(realBox);
    if (lower.top - upper.bottom < STACKED_GAP_THRESHOLD) return null;
    // A third node in the gap leaves no room to return through it; the wire goes around.
    const gap: Box = {
        left: Math.min(upper.left, lower.left),
        right: Math.max(upper.right, lower.right),
        top: upper.bottom,
        bottom: lower.top,
    };
    for (const other of nodesById.values()) {
        if (other === source || other === target) continue;
        const box = realBox(other);
        if (
            rangesOverlap(box.left, box.right, gap.left, gap.right) &&
            rangesOverlap(box.top, box.bottom, gap.top, gap.bottom)
        ) {
            return null;
        }
    }
    return { upper, lower };
}

function orientation(first: IPoint, second: IPoint, third: IPoint): number {
    const value = (second.x - first.x) * (third.y - first.y) - (second.y - first.y) * (third.x - first.x);
    return Math.abs(value) < 1e-9 ? 0 : Math.sign(value);
}

// Proper crossing: each segment strictly separates the other's end points. A T-junction, a
// shared end point or a collinear overlap is not a crossing.
function segmentsCross(startA: IPoint, endA: IPoint, startB: IPoint, endB: IPoint): boolean {
    const o1 = orientation(startA, endA, startB);
    const o2 = orientation(startA, endA, endB);
    const o3 = orientation(startB, endB, startA);
    const o4 = orientation(startB, endB, endA);
    return o1 !== 0 && o2 !== 0 && o3 !== 0 && o4 !== 0 && o1 !== o2 && o3 !== o4;
}

function countCrossings(wires: RoutedWire[]): number {
    let count = 0;
    for (let first = 0; first < wires.length; first++) {
        for (let second = first + 1; second < wires.length; second++) {
            const a = wires[first].points;
            const b = wires[second].points;
            for (let segmentA = 0; segmentA < a.length - 1; segmentA++) {
                for (let segmentB = 0; segmentB < b.length - 1; segmentB++) {
                    if (segmentsCross(a[segmentA], a[segmentA + 1], b[segmentB], b[segmentB + 1])) count++;
                }
            }
        }
    }
    return count;
}

function boundingArea(nodes: NodeModel[]): number {
    if (nodes.length === 0) return 0;
    const boxes = nodes.map(realBox);
    const width = Math.max(...boxes.map((box) => box.right)) - Math.min(...boxes.map((box) => box.left));
    const height = Math.max(...boxes.map((box) => box.bottom)) - Math.min(...boxes.map((box) => box.top));
    return width * height;
}
