import { IPoint } from '@foblex/2d';

import {
    firstIndexAbove,
    firstIndexAtOrAbove,
    RoutingGrid,
    STEP_BLOCKED,
    STEP_ON_EDGE,
    STEP_SQUEEZED,
} from './routing-grid';

/**
 * A* over the routing grid with the heading in the state. Cost = length
 * + BEND_COST per heading change + CROSSING_COST per crossed wire + SHARED_COST per px run on
 * top of another wire (+ PINNED_SHARED_COST per px on another wire's first or last segment).
 * Pure and deterministic: every tie breaks on (f, g, yi, xi, heading).
 * EDGE_COST is only a tie-breaker: among routes otherwise equal, the one in the
 * middle of a channel wins over one along a node's padding (the Py#14 → Py#15 fixture's leg in the gap's middle).
 * It is small enough that two extra bends (60) only pay off against an edge run over 3000 px.
 */

const BEND_COST = 30;
const CROSSING_COST = 60;
const SHARED_COST = 2;
const EDGE_COST = 0.02;
// How far past the start/goal bounding box the first search looks. A detour wider than this is
// found by the retry over the whole grid, only when the window holds no route at all.
const SEARCH_MARGIN = 400;
// A wire's first and last segments sit on its port rows and nudging never moves them, so running
// on top of one can't be undone later: a flat price for any overlap, even 2 px,
// plus a crossing's worth every 2 px. The same for any wire in a squeezed step (two padded boxes
// touching): nudging has no room there to move either wire aside. And for turning off the own start
// row, or onto the own goal row, where another wire's first or last segment carries on along that
// row end to end: the two read as one wire running through, and nudging can't move the turn aside
// without running one on top of the other.
const PINNED_OVERLAP_COST = 400;
const PINNED_SHARED_COST = 30;
// The stub: the first/last STUB px of a wire, from the port to the search's start/goal.
const STUB = 20;
// An interior segment shorter than this reads as a kink. Ending one costs more than running
// 400 px on top of another wire (which nudging separates), so the search avoids it wherever it can.
const MIN_INTERIOR_SEGMENT = 10;
const SHORT_SEGMENT_COST = 400;
// The quality checker's sub-pixel tolerance: a 9.5-px segment is not short.
const LENGTH_TOLERANCE = 0.5;

/**
 * Optional limits on a search. `rows`: only grid rows within [top, bottom] may be used.
 * `legsAbove`: between the goal and start columns (exclusive) only rows at or above this y may be
 * used, so every leg crossing that span runs there; the risers beside the stubs are free.
 */
export interface RouteOptions {
    rows?: { top: number; bottom: number };
    legsAbove?: number;
}

export interface OwnPorts {
    source: string;
    target: string;
}

interface OccupiedWire {
    source: number; // interned port keys: integer compares
    target: number;
    points: IPoint[];
}

/**
 * Wires already routed (or frozen). The search reads their cost from per-grid arrays, one cell per
 * grid point or step, so a step's penalty is O(1); `crossings` and `sharedLength` are the plain
 * definitions the arrays reproduce. Wires that share a source or target port with the wire being
 * routed are a trunk: they neither cost a crossing nor a shared length.
 */
export class SegmentIndex {
    private readonly wires: OccupiedWire[] = [];
    private readonly portIds = new Map<string, number>();
    private penalties: GridPenalties | null = null;

    add(wire: { id: string; sourcePortKey: string; targetPortKey: string; points: IPoint[] }): void {
        this.wires.push({
            source: this.portId(wire.sourcePortKey),
            target: this.portId(wire.targetPortKey),
            points: wire.points,
        });
    }

    /**
     * Perpendicular wires this step crosses. A wire is counted where the step arrives at its line
     * (the interval is open at `from`, closed at `to`), so consecutive steps never count it twice.
     */
    crossings(from: IPoint, to: IPoint, ownPorts: OwnPorts): number {
        const horizontal = from.y === to.y;
        const stepFrom = horizontal ? from.x : from.y;
        const stepTo = horizontal ? to.x : to.y;
        const position = horizontal ? from.y : from.x;
        let count = 0;
        for (const wire of this.othersThan(ownPorts)) {
            forEachAxisSegment(wire.points, (segmentHorizontal, line, low, high) => {
                if (segmentHorizontal === horizontal) return;
                const reached =
                    stepTo > stepFrom ? line > stepFrom && line <= stepTo : line >= stepTo && line < stepFrom;
                if (reached && low < position && position < high) count++;
            });
        }
        return count;
    }

    /** Length this step runs collinearly on top of wires that share neither port with it. */
    sharedLength(from: IPoint, to: IPoint, ownPorts: OwnPorts): number {
        const horizontal = from.y === to.y;
        const line = horizontal ? from.y : from.x;
        const low = horizontal ? Math.min(from.x, to.x) : Math.min(from.y, to.y);
        const high = horizontal ? Math.max(from.x, to.x) : Math.max(from.y, to.y);
        let shared = 0;
        for (const wire of this.othersThan(ownPorts)) {
            forEachAxisSegment(wire.points, (segmentHorizontal, segmentLine, segmentLow, segmentHigh) => {
                if (segmentHorizontal !== horizontal || segmentLine !== line) return;
                shared += Math.max(0, Math.min(high, segmentHigh) - Math.max(low, segmentLow));
            });
        }
        return shared;
    }

    /** The penalty arrays for `grid`, holding every wire added so far. One grid is cached at a time. */
    penaltiesFor(grid: RoutingGrid): GridPenalties {
        if (this.penalties?.grid !== grid) this.penalties = new GridPenalties(grid);
        const penalties = this.penalties;
        for (; penalties.drawnWires < this.wires.length; penalties.drawnWires++) {
            penalties.draw(this.wires[penalties.drawnWires].points, 1);
        }
        return penalties;
    }

    /** The wires that share the source or the target port: the trunk of the wire being routed. */
    trunkOf(ownPorts: OwnPorts): OccupiedWire[] {
        const [source, target] = this.ownIds(ownPorts);
        return this.wires.filter((wire) => wire.source === source || wire.target === target);
    }

    private othersThan(ownPorts: OwnPorts): OccupiedWire[] {
        const [source, target] = this.ownIds(ownPorts);
        return this.wires.filter((wire) => wire.source !== source && wire.target !== target);
    }

    private portId(portKey: string): number {
        let id = this.portIds.get(portKey);
        if (id === undefined) {
            id = this.portIds.size;
            this.portIds.set(portKey, id);
        }
        return id;
    }

    // A port key never added gets -1, which matches no wire.
    private ownIds(ownPorts: OwnPorts): [number, number] {
        return [this.portIds.get(ownPorts.source) ?? -1, this.portIds.get(ownPorts.target) ?? -1];
    }
}

/**
 * Occupied wires drawn into one grid (index = row x columns + column, as the grid's steps):
 * - `*Through`: segments passing strictly through a grid point, crossed by a perpendicular step
 *   that arrives there;
 * - `*StepCrossings`: segments on a line between two grid lines (only frozen hand-made wires lie
 *   off the grid), crossed by the perpendicular step that spans that line;
 * - `*Shared`: the length of segments on top of a step.
 * `horizontalThrough` and `horizontalShared` hold horizontal segments, `horizontalStepCrossings`
 * the vertical ones a horizontal step spans; the vertical arrays mirror them.
 */
class GridPenalties {
    readonly horizontalThrough: Int32Array;
    readonly verticalThrough: Int32Array;
    readonly horizontalStepCrossings: Int32Array;
    readonly verticalStepCrossings: Int32Array;
    readonly horizontalShared: Float64Array;
    readonly verticalShared: Float64Array;
    readonly horizontalPinnedShared: Float64Array; // the part of horizontalShared on first/last segments
    drawnWires = 0;

    constructor(readonly grid: RoutingGrid) {
        const cells = grid.xs.length * grid.ys.length;
        this.horizontalThrough = new Int32Array(cells);
        this.verticalThrough = new Int32Array(cells);
        this.horizontalStepCrossings = new Int32Array(cells);
        this.verticalStepCrossings = new Int32Array(cells);
        this.horizontalShared = new Float64Array(cells);
        this.verticalShared = new Float64Array(cells);
        this.horizontalPinnedShared = new Float64Array(cells);
    }

    /** Adds (sign 1) or removes (sign -1) a wire's segments. */
    draw(points: IPoint[], sign: number): void {
        const { xs, ys } = this.grid;
        const columns = xs.length;
        const lastPair = points.length - 2;
        forEachAxisSegment(points, (horizontal, line, low, high, pair) => {
            const pinned = horizontal && (pair === 0 || pair === lastPair);
            // `along` is the segment's own axis (xs for a horizontal one), `across` the other.
            const along = horizontal ? xs : ys;
            const across = horizontal ? ys : xs;
            const cell = (alongIndex: number, acrossIndex: number): number =>
                horizontal ? acrossIndex * columns + alongIndex : alongIndex * columns + acrossIndex;
            const firstInside = firstIndexAbove(along, low);
            const lastInside = firstIndexAtOrAbove(along, high) - 1;
            const lineIndex = horizontal ? this.grid.indexOfY(line) : this.grid.indexOfX(line);
            if (lineIndex >= 0) {
                const through = horizontal ? this.horizontalThrough : this.verticalThrough;
                const shared = horizontal ? this.horizontalShared : this.verticalShared;
                for (let index = firstInside; index <= lastInside; index++) through[cell(index, lineIndex)] += sign;
                for (
                    let index = Math.max(0, firstInside - 1);
                    index < along.length - 1 && along[index] < high;
                    index++
                ) {
                    const overlap = Math.min(high, along[index + 1]) - Math.max(low, along[index]);
                    if (overlap <= 0) continue;
                    shared[cell(index, lineIndex)] += sign * overlap;
                    if (pinned) this.horizontalPinnedShared[cell(index, lineIndex)] += sign * overlap;
                }
                return;
            }
            // Off the grid: crossed by the perpendicular steps between the two lines around it.
            const before = firstIndexAbove(across, line) - 1;
            if (before < 0 || before >= across.length - 1) return;
            const stepCrossings = horizontal ? this.verticalStepCrossings : this.horizontalStepCrossings;
            for (let index = firstInside; index <= lastInside; index++) stepCrossings[cell(index, before)] += sign;
        });
    }
}

/**
 * Calls `visit` for each axis-parallel piece of a polyline, with the index of the point pair it
 * belongs to; a diagonal pair (possible in hand-made waypoints) counts as horizontal-then-vertical.
 * Zero-length pieces are skipped.
 */
function forEachAxisSegment(
    points: IPoint[],
    visit: (horizontal: boolean, line: number, low: number, high: number, pair: number) => void
): void {
    for (let index = 0; index < points.length - 1; index++) {
        const start = points[index];
        const end = points[index + 1];
        if (start.x !== end.x) visit(true, start.y, Math.min(start.x, end.x), Math.max(start.x, end.x), index);
        if (start.y !== end.y) visit(false, end.x, Math.min(start.y, end.y), Math.max(start.y, end.y), index);
    }
}

const EAST = 0;
const WEST = 1;
const NORTH = 2;
const SOUTH = 3;
const REVERSE = [WEST, EAST, SOUTH, NORTH];
const STEP_X = [1, -1, 0, 0];
const STEP_Y = [0, 0, -1, 1]; // canvas y grows downwards: north is up

/**
 * The cheapest orthogonal route from the source stub end (arrived at heading east) to the target
 * stub end, from which the last stub continues east into the port. Returns the points from stub
 * end to stub end with collinear points removed, or null when the goal can't be reached.
 * A start inside an obstacle (overlapping nodes) may walk out of it; nothing may walk into one.
 * The route never passes through its own stubs (the STUB px west of `start` and east of `goal`).
 */
export function findRoute(
    grid: RoutingGrid,
    start: IPoint,
    goal: IPoint,
    occupied: SegmentIndex,
    ownPorts: OwnPorts,
    options: RouteOptions = {}
): IPoint[] | null {
    const startXi = grid.indexOfX(start.x);
    const startYi = grid.indexOfY(start.y);
    const goalXi = grid.indexOfX(goal.x);
    const goalYi = grid.indexOfY(goal.y);
    if (startXi < 0 || startYi < 0 || goalXi < 0 || goalYi < 0) return null;

    const penalties = occupied.penaltiesFor(grid);
    const trunk = occupied.trunkOf(ownPorts);
    for (const wire of trunk) penalties.draw(wire.points, -1);
    try {
        // First inside the start/goal box widened by SEARCH_MARGIN, then everywhere: when that finds
        // nothing, or only a route on top of a wire nudging can't move aside (an overlap for good), which
        // a way round outside the window may avoid (over a tall node stacked 20 px on another).
        const search = (margin: number): IPoint[] | null =>
            searchRoute(
                grid,
                startXi,
                startYi,
                goalXi,
                goalYi,
                penalties,
                searchWindow(grid, start, goal, margin, options),
                options.legsAbove ?? Number.POSITIVE_INFINITY
            );
        const windowed = search(SEARCH_MARGIN);
        if (windowed && !runsOnUnmovableWire(grid, penalties, windowed, startYi, goalYi)) return windowed;
        return search(Number.POSITIVE_INFINITY) ?? windowed;
    } finally {
        for (const wire of trunk) penalties.draw(wire.points, 1);
    }
}

/**
 * Whether a found route (grid points) runs on top of another wire where the search charges
 * PINNED_OVERLAP_COST: another wire's first or last segment, the own first or last row heading east,
 * or a squeezed step.
 */
function runsOnUnmovableWire(
    grid: RoutingGrid,
    penalties: GridPenalties,
    points: IPoint[],
    startYi: number,
    goalYi: number
): boolean {
    const columns = grid.xs.length;
    for (let index = 0; index < points.length - 1; index++) {
        const [from, to] = [points[index], points[index + 1]];
        if (from.y === to.y) {
            const yi = grid.indexOfY(from.y);
            const ownPinned = to.x > from.x && (yi === startYi || yi === goalYi);
            const last = grid.indexOfX(Math.max(from.x, to.x));
            for (let xi = grid.indexOfX(Math.min(from.x, to.x)); xi < last; xi++) {
                const cell = yi * columns + xi;
                const squeezed = (grid.horizontalSteps[cell] & STEP_SQUEEZED) === STEP_SQUEEZED;
                const shared = penalties.horizontalShared[cell];
                if (penalties.horizontalPinnedShared[cell] > 0 || ((ownPinned || squeezed) && shared > 0)) return true;
            }
        } else {
            const xi = grid.indexOfX(from.x);
            const last = grid.indexOfY(Math.max(from.y, to.y));
            for (let yi = grid.indexOfY(Math.min(from.y, to.y)); yi < last; yi++) {
                const cell = yi * columns + xi;
                const squeezed = (grid.verticalSteps[cell] & STEP_SQUEEZED) === STEP_SQUEEZED;
                if (squeezed && penalties.verticalShared[cell] > 0) return true;
            }
        }
    }
    return false;
}

// The hot loop: plain typed-array reads, no closures.
function searchRoute(
    grid: RoutingGrid,
    startXi: number,
    startYi: number,
    goalXi: number,
    goalYi: number,
    penalties: GridPenalties,
    window: SearchWindow,
    legsAbove: number
): IPoint[] | null {
    const { xs, ys, pointBlocked, horizontalSteps, verticalSteps } = grid;
    const columns = xs.length;
    const goalX = xs[goalXi];
    const goalY = ys[goalYi];
    const startX = xs[startXi];
    const { firstXi, lastXi, firstYi, lastYi } = window;
    const {
        horizontalThrough,
        verticalThrough,
        horizontalStepCrossings,
        verticalStepCrossings,
        horizontalShared,
        verticalShared,
        horizontalPinnedShared,
    } = penalties;
    const scratch = scratchFor(grid, columns * ys.length * 4);
    const generation = ++scratch.generation;
    const { stamp, cost: costs, parent, open } = scratch;
    open.clear();

    const startState = (startYi * columns + startXi) * 4 + EAST;
    stamp[startState] = generation;
    costs[startState] = 0;
    parent[startState] = -1;
    const startHeuristic =
        Math.abs(goalX - startX) +
        Math.abs(goalY - ys[startYi]) +
        BEND_COST * minimumBends(EAST, goalX - startX, goalY - ys[startYi]);
    open.push(startHeuristic, 0, startState, startState);
    // Reaching the goal cell heading anywhere but west can finish: the last stub turns east.
    // A finish is queued as the entry -1 - state, costing one more bend unless it arrives east.
    if (startXi === goalXi && startYi === goalYi) open.push(0, 0, startState, -1 - startState);

    while (open.size > 0) {
        const cost = open.topCost;
        const entry = open.pop();
        if (entry < 0) {
            const finishedState = -1 - entry;
            const finishCost = finishTurnCost(parent, finishedState, columns, xs, ys, horizontalPinnedShared);
            if (cost !== costs[finishedState] + finishCost) continue; // stale
            return tracePath(parent, finishedState, columns, xs, ys);
        }
        if (cost > costs[entry]) continue; // stale
        const heading = entry & 3;
        const cell = entry >> 2;
        const xi = cell % columns;
        const yi = (cell - xi) / columns;
        const escaping = pointBlocked[cell] === 1;
        const fromX = xs[xi];
        const fromY = ys[yi];

        for (let direction = 0; direction < 4; direction++) {
            if (direction === REVERSE[heading]) continue;
            const nextXi = xi + STEP_X[direction];
            const nextYi = yi + STEP_Y[direction];
            if (nextXi < firstXi || nextYi < firstYi || nextXi > lastXi || nextYi > lastYi) continue;
            const toX = xs[nextXi];
            const toY = ys[nextYi];
            if (toY > legsAbove && toX > goalX && toX < startX) continue;
            // Never through the own stubs: that would cross the wire's first or last segment.
            if (nextYi === startYi && toX < startX && toX > startX - STUB) continue;
            if (nextYi === goalYi && toX > goalX && toX < goalX + STUB) continue;
            const horizontal = direction === EAST || direction === WEST;
            const stepCell = horizontal
                ? yi * columns + (direction === EAST ? xi : nextXi)
                : (direction === SOUTH ? yi : nextYi) * columns + xi;
            const flags = horizontal ? horizontalSteps[stepCell] : verticalSteps[stepCell];
            if ((flags & STEP_BLOCKED) !== 0 && !escaping) continue;

            const length = horizontal ? Math.abs(toX - fromX) : Math.abs(toY - fromY);
            const arrivalCell = nextYi * columns + nextXi;
            let penalty: number;
            if (horizontal) {
                // Heading east on the own start or goal row is (as good as always) the own first or
                // last segment: pinned too, so running on top of any wire there can't be undone either.
                const ownPinned = direction === EAST && (yi === startYi || yi === goalYi);
                const squeezed = (flags & STEP_SQUEEZED) === STEP_SQUEEZED;
                const pinnedOverlap =
                    ownPinned || squeezed ? horizontalShared[stepCell] : horizontalPinnedShared[stepCell];
                penalty =
                    CROSSING_COST * (verticalThrough[arrivalCell] + horizontalStepCrossings[stepCell]) +
                    SHARED_COST * horizontalShared[stepCell] +
                    (pinnedOverlap > 0 ? PINNED_OVERLAP_COST + PINNED_SHARED_COST * pinnedOverlap : 0);
            } else {
                const squeezedOverlap = (flags & STEP_SQUEEZED) === STEP_SQUEEZED ? verticalShared[stepCell] : 0;
                penalty =
                    CROSSING_COST * (horizontalThrough[arrivalCell] + verticalStepCrossings[stepCell]) +
                    SHARED_COST * verticalShared[stepCell] +
                    (squeezedOverlap > 0 ? PINNED_OVERLAP_COST + PINNED_SHARED_COST * squeezedOverlap : 0);
            }
            let bendCost = 0;
            if (direction !== heading) {
                bendCost = BEND_COST + shortSegmentCost(parent, entry, false, columns, xs, ys);
                const leavesStartRow = heading === EAST && !horizontal && yi === startYi;
                if (leavesStartRow && horizontalPinnedShared[cell] > 0 && isOnFirstSegment(parent, entry)) {
                    bendCost += PINNED_OVERLAP_COST;
                } else if (direction === EAST && yi === goalYi && xi > 0 && horizontalPinnedShared[cell - 1] > 0) {
                    bendCost += PINNED_OVERLAP_COST;
                }
            }
            const nextCost =
                cost + length + ((flags & STEP_ON_EDGE) !== 0 ? EDGE_COST * length : 0) + bendCost + penalty;
            const nextState = arrivalCell * 4 + direction;
            if (stamp[nextState] === generation && nextCost >= costs[nextState]) continue;
            stamp[nextState] = generation;
            costs[nextState] = nextCost;
            parent[nextState] = entry;
            const heuristic =
                Math.abs(goalX - toX) +
                Math.abs(goalY - toY) +
                BEND_COST * minimumBends(direction, goalX - toX, goalY - toY);
            open.push(nextCost + heuristic, nextCost, nextState, nextState);
            if (nextXi === goalXi && nextYi === goalYi && direction !== WEST) {
                const total = nextCost + finishTurnCost(parent, nextState, columns, xs, ys, horizontalPinnedShared);
                open.push(total, total, nextState, -1 - nextState);
            }
        }
    }
    return null;
}

// Finishing at the goal: a final turn east into the last stub is a bend, and ends a segment; with
// another wire's first or last segment ending there from the west, a continuation.
function finishTurnCost(
    parent: Int32Array,
    state: number,
    columns: number,
    xs: readonly number[],
    ys: readonly number[],
    pinnedShared: Float64Array
): number {
    if ((state & 3) === EAST) return 0;
    const cell = state >> 2;
    const continuation = cell % columns > 0 && pinnedShared[cell - 1] > 0 ? PINNED_OVERLAP_COST : 0;
    return BEND_COST + shortSegmentCost(parent, state, true, columns, xs, ys) + continuation;
}

/**
 * SHORT_SEGMENT_COST when turning at `state` ends an interior segment shorter than
 * MIN_INTERIOR_SEGMENT, found by walking the parent chain back to where the segment began. The
 * first segment holds the start stub and is never short. At the finish, a segment right after the
 * first one is the only one between the two stubs: its length is the ports' vertical offset, so
 * there is nothing to avoid (a detour would only add bends). Path-dependent, so it steers the
 * search rather than being part of the exact cost.
 */
function shortSegmentCost(
    parent: Int32Array,
    state: number,
    finishing: boolean,
    columns: number,
    xs: readonly number[],
    ys: readonly number[]
): number {
    const heading = state & 3;
    let length = 0;
    for (let current = state; ; ) {
        const previous = parent[current];
        if (previous < 0) return 0;
        const [from, to] = [previous >> 2, current >> 2];
        length +=
            Math.abs(xs[to % columns] - xs[from % columns]) +
            Math.abs(ys[(to / columns) | 0] - ys[(from / columns) | 0]);
        if (length >= MIN_INTERIOR_SEGMENT - LENGTH_TOLERANCE) return 0;
        if ((previous & 3) !== heading) {
            return finishing && isOnFirstSegment(parent, previous) ? 0 : SHORT_SEGMENT_COST;
        }
        current = previous;
    }
}

// Whether `state` lies on the first segment: every step back to the start heads east.
function isOnFirstSegment(parent: Int32Array, state: number): boolean {
    for (let current = state; current >= 0; current = parent[current]) {
        if ((current & 3) !== EAST) return false;
    }
    return true;
}

interface SearchWindow {
    firstXi: number;
    lastXi: number;
    firstYi: number;
    lastYi: number;
}

// The grid lines within `margin` of the start/goal bounding box (all of them for an infinite
// margin), and rows only within `options.rows` when given.
function searchWindow(
    grid: RoutingGrid,
    start: IPoint,
    goal: IPoint,
    margin: number,
    options: RouteOptions
): SearchWindow {
    const { xs, ys } = grid;
    const top = Math.max(Math.min(start.y, goal.y) - margin, options.rows?.top ?? Number.NEGATIVE_INFINITY);
    const bottom = Math.min(Math.max(start.y, goal.y) + margin, options.rows?.bottom ?? Number.POSITIVE_INFINITY);
    return {
        firstXi: firstIndexAtOrAbove(xs, Math.min(start.x, goal.x) - margin),
        lastXi: firstIndexAbove(xs, Math.max(start.x, goal.x) + margin) - 1,
        firstYi: firstIndexAtOrAbove(ys, top),
        lastYi: firstIndexAbove(ys, bottom) - 1,
    };
}

/**
 * The fewest heading changes, the final turn east into the stub included, from `heading` to a
 * goal `deltaX, deltaY` away in open space. Exact without obstacles, so admissible with them.
 * A goal with deltaX = 0 counts as east: the last stub leaves it eastwards.
 */
function minimumBends(heading: number, deltaX: number, deltaY: number): number {
    const toward = deltaY < 0 ? NORTH : SOUTH;
    if (deltaX >= 0) {
        if (deltaY === 0) return heading === EAST ? 0 : heading === WEST ? 4 : 1;
        if (heading === EAST || heading === WEST) return 2;
        return heading === toward ? 1 : 3;
    }
    if (deltaY === 0) return heading === EAST || heading === WEST ? 4 : 3;
    if (heading === WEST) return 2;
    return heading === EAST ? 4 : 3;
}

function tracePath(
    parent: Int32Array,
    lastState: number,
    columns: number,
    xs: readonly number[],
    ys: readonly number[]
): IPoint[] {
    const cells: IPoint[] = [];
    for (let state = lastState; state >= 0; state = parent[state]) {
        const cell = state >> 2;
        cells.push({ x: xs[cell % columns], y: ys[Math.floor(cell / columns)] });
    }
    cells.reverse();
    return cells.filter((point, index) => {
        if (index === 0 || index === cells.length - 1) return true;
        const previous = cells[index - 1];
        const next = cells[index + 1];
        return !((previous.x === point.x && point.x === next.x) || (previous.y === point.y && point.y === next.y));
    });
}

interface SearchScratch {
    generation: number;
    stamp: Uint32Array; // a state's cost/parent are valid only when its stamp equals the generation
    cost: Float64Array;
    parent: Int32Array;
    open: SearchHeap;
}

// One set of buffers per grid, reused by every search on it; routeAll builds one grid per run.
const scratchByGrid = new WeakMap<RoutingGrid, SearchScratch>();

function scratchFor(grid: RoutingGrid, stateCount: number): SearchScratch {
    let scratch = scratchByGrid.get(grid);
    if (!scratch) {
        scratch = {
            generation: 0,
            stamp: new Uint32Array(stateCount),
            cost: new Float64Array(stateCount),
            parent: new Int32Array(stateCount),
            open: new SearchHeap(),
        };
        scratchByGrid.set(grid, scratch);
    }
    return scratch;
}

/**
 * Binary min-heap on (priority, cost, tie) in typed arrays that grow by doubling. `entry` is a
 * state, or -1 - state for a finished route. Sifts move a hole instead of swapping.
 */
class SearchHeap {
    size = 0;
    private priorities = new Float64Array(1024);
    private costs = new Float64Array(1024);
    private ties = new Int32Array(1024);
    private entries = new Int32Array(1024);

    get topCost(): number {
        return this.costs[0];
    }

    clear(): void {
        this.size = 0;
    }

    push(priority: number, cost: number, tie: number, entry: number): void {
        if (this.size === this.entries.length) this.grow();
        const { priorities, costs, ties, entries } = this;
        let index = this.size++;
        while (index > 0) {
            const parent = (index - 1) >> 1;
            if (!isBefore(priority, cost, tie, priorities[parent], costs[parent], ties[parent])) break;
            priorities[index] = priorities[parent];
            costs[index] = costs[parent];
            ties[index] = ties[parent];
            entries[index] = entries[parent];
            index = parent;
        }
        priorities[index] = priority;
        costs[index] = cost;
        ties[index] = tie;
        entries[index] = entry;
    }

    pop(): number {
        const { priorities, costs, ties, entries } = this;
        const top = entries[0];
        const size = --this.size;
        if (size === 0) return top;
        const priority = priorities[size];
        const cost = costs[size];
        const tie = ties[size];
        const entry = entries[size];
        let index = 0;
        for (;;) {
            const left = index * 2 + 1;
            if (left >= size) break;
            const right = left + 1;
            const child =
                right < size &&
                isBefore(priorities[right], costs[right], ties[right], priorities[left], costs[left], ties[left])
                    ? right
                    : left;
            if (!isBefore(priorities[child], costs[child], ties[child], priority, cost, tie)) break;
            priorities[index] = priorities[child];
            costs[index] = costs[child];
            ties[index] = ties[child];
            entries[index] = entries[child];
            index = child;
        }
        priorities[index] = priority;
        costs[index] = cost;
        ties[index] = tie;
        entries[index] = entry;
        return top;
    }

    private grow(): void {
        const capacity = this.entries.length * 2;
        const grown = <T extends Float64Array | Int32Array>(values: T, make: (length: number) => T): T => {
            const next = make(capacity);
            next.set(values);
            return next;
        };
        this.priorities = grown(this.priorities, (length) => new Float64Array(length));
        this.costs = grown(this.costs, (length) => new Float64Array(length));
        this.ties = grown(this.ties, (length) => new Int32Array(length));
        this.entries = grown(this.entries, (length) => new Int32Array(length));
    }
}

// Lower priority first, then lower cost, then lower tie (the state index: yi, xi, heading).
function isBefore(
    priority: number,
    cost: number,
    tie: number,
    otherPriority: number,
    otherCost: number,
    otherTie: number
): boolean {
    if (priority !== otherPriority) return priority < otherPriority;
    if (cost !== otherCost) return cost < otherCost;
    return tie < otherTie;
}
