import { IPoint } from '@foblex/2d';

import { Rect } from './obstacles';

/**
 * Separates wires that run on top of each other into parallel lanes. Collinear
 * overlapping segments of different wires form a group; wires sharing a source or a target port
 * are one trunk and share a lane. Lanes are ordered so that no wire has to cross another where it
 * leaves the shared run, spaced `min(LANE_SPACING, channel / (lanes + 1))` apart and kept inside
 * the free channel between obstacles. The first and last segments (the stubs) never move; a lane
 * next to a stub stays STUB from the port. `fixed` wires (hand-edited ones) never move but hold
 * their lane: the others are laid out beside them. Pure and deterministic.
 */

export interface RoutedPath {
    id: string;
    sourcePortKey: string;
    targetPortKey: string;
    points: IPoint[]; // full points, port to port
}

const LANE_SPACING = 10;
const STUB = 20;
// A lane may shorten a neighbouring segment down to this, never flip it.
const MIN_SEGMENT = 1;
const ROUNDS = 2;
// Halvings of the spacing tried before a group that can't be fitted is left as it is.
const SPACING_ATTEMPTS = 4;
// Two parallel segments closer than this are drawn on the same pixel row (as the quality checker counts).
const SAME_LINE_TOLERANCE = 0.5;
// Parallel segments of different wires closer than a lane apart, side by side for longer than
// NEAR_OVERLAP, read as one thick wire: they are spread into lanes like collinear ones.
const NEAR_DISTANCE = LANE_SPACING - SAME_LINE_TOLERANCE;
const NEAR_OVERLAP = 5;
// Collinear segments of different wires that meet end to end, or leave a gap of up to this, read as
// one wire running through (two risers into one column, one above the other): lanes as well.
const END_TO_END_GAP = 20;
// In the acceptance score a collinear overlap outweighs any number of merely close pairs.
const COLLINEAR_WEIGHT = 1000;

type Axis = 'x' | 'y'; // 'x': vertical segments, moved along x; 'y': horizontal ones, moved along y

interface Segment {
    path: number; // index into the paths
    index: number; // the segment runs from points[index] to points[index + 1]
    line: number; // its x (vertical) or y (horizontal)
    low: number; // its extent along the line
    high: number;
}

export function nudgePaths(paths: RoutedPath[], obstacles: Rect[], fixed: RoutedPath[] = []): RoutedPath[] {
    const working = [...paths, ...fixed].map((routed) => ({
        ...routed,
        points: routed.points.map((point) => ({ ...point })),
    }));
    for (let round = 0; round < ROUNDS; round++) {
        nudgeAxis(working, paths.length, obstacles, 'x');
        nudgeAxis(working, paths.length, obstacles, 'y');
    }
    return working.slice(0, paths.length);
}

// Paths from index `firstFixed` on are fixed.
// Collinear groups first, then the close-but-apart ones: a cluster of close lanes that can't be
// fitted must not keep a collinear overlap inside it from being separated.
function nudgeAxis(paths: RoutedPath[], firstFixed: number, obstacles: Rect[], axis: Axis): void {
    const lines = new SegmentLines(paths);
    for (const includeNear of [false, true]) {
        for (const group of overlapGroups(paths, axis, includeNear)) {
            const lanes = trunkLanes(paths, orderLanes(paths, wireLanes(group), axis));
            if (lanes.length > 1) placeLanes(paths, firstFixed, lines, lanes, obstacles, axis);
        }
    }
}

// Interior segments along the axis (the stubs never move), grouped into clusters that involve
// more than one wire: segments on one line whose extents overlap, and with `includeNear` also
// parallel segments of different wires less than a lane apart that run side by side (NEAR_OVERLAP),
// and collinear ones of different wires end to end (END_TO_END_GAP).
function overlapGroups(paths: RoutedPath[], axis: Axis, includeNear: boolean): Segment[][] {
    const along: Axis = axis === 'x' ? 'y' : 'x';
    const segments: Segment[] = [];
    paths.forEach((routed, pathIndex) => {
        const { points } = routed;
        for (let index = 1; index < points.length - 2; index++) {
            const start = points[index];
            const end = points[index + 1];
            if (start[axis] !== end[axis] || start[along] === end[along]) continue;
            segments.push({
                path: pathIndex,
                index,
                line: start[axis],
                low: Math.min(start[along], end[along]),
                high: Math.max(start[along], end[along]),
            });
        }
    });
    segments.sort(
        (first, second) =>
            first.line - second.line ||
            first.low - second.low ||
            compareIds(paths[first.path].id, paths[second.path].id) ||
            first.index - second.index
    );

    const parent = segments.map((_, index) => index);
    const root = (index: number): number => {
        while (parent[index] !== index) index = parent[index] = parent[parent[index]];
        return index;
    };
    for (let first = 0; first < segments.length; first++) {
        for (let second = first + 1; second < segments.length; second++) {
            const [a, b] = [segments[first], segments[second]];
            if (b.line !== a.line && (!includeNear || b.line - a.line >= NEAR_DISTANCE)) break;
            const overlap = Math.min(a.high, b.high) - Math.max(a.low, b.low);
            const endToEnd = includeNear && a.path !== b.path && overlap <= 0 && overlap >= -END_TO_END_GAP;
            const conflicts = a.line === b.line ? overlap > 0 || endToEnd : a.path !== b.path && overlap > NEAR_OVERLAP;
            if (conflicts) parent[root(second)] = root(first);
        }
    }
    const clusters = new Map<number, Segment[]>();
    segments.forEach((segment, index) => {
        const key = root(index);
        const cluster = clusters.get(key);
        if (cluster) cluster.push(segment);
        else clusters.set(key, [segment]);
    });
    return [...clusters.values()].filter((cluster) => new Set(cluster.map((member) => member.path)).size > 1);
}

// One lane per wire and line: a wire's segments on two close lines are two lanes. In the group's
// order (line, low end, id), so deterministic.
function wireLanes(group: Segment[]): Segment[][] {
    const lanes = new Map<string, Segment[]>();
    for (const segment of group) {
        const key = `${segment.line}|${segment.path}`;
        const lane = lanes.get(key);
        if (lane) lane.push(segment);
        else lanes.set(key, [segment]);
    }
    return [...lanes.values()];
}

// Neighbouring lanes (in the crossing-free order) on one line whose wires each share a source or a
// target port with every wire already in the lane are a trunk: one lane. Not transitive: when A
// shares a source with B and B a target with C, A and C share nothing and must not overlap, so C
// gets a lane of its own. Wires sharing a port that aren't neighbours keep their own lanes: the
// wire ordered between them would otherwise cross the trunk (flow 6: Py#5's stub between Py#4's
// and Py#6's risers into one table).
function trunkLanes(paths: RoutedPath[], orderedLanes: Segment[][]): Segment[][] {
    const merged: Segment[][] = [];
    for (const lane of orderedLanes) {
        const previous = merged[merged.length - 1];
        const wire = paths[lane[0].path];
        const joins =
            previous !== undefined &&
            previous[0].line === lane[0].line &&
            previous.every((member) => sharesPort(paths[member.path], wire));
        if (joins) previous.push(...lane);
        else merged.push([...lane]);
    }
    return merged;
}

function sharesPort(first: RoutedPath, second: RoutedPath): boolean {
    return first.sourcePortKey === second.sourcePortKey || first.targetPortKey === second.targetPortKey;
}

interface LaneEnds {
    id: string; // the representative wire's id, for ties
    low: number;
    high: number;
    lowSide: number; // −1 / +1: the neighbouring segment at the low end heads to the lower / higher coordinate
    highSide: number;
    lowIsStub: boolean; // the neighbouring segment at the low end is the wire's first or last one
    highIsStub: boolean;
}

// Lanes from the lower coordinate (left / up) to the higher one, by where their wires leave the
// shared run; lanes a few px apart are ordered the same way, which also undoes crossings between them.
function orderLanes(paths: RoutedPath[], bundles: Segment[][], axis: Axis): Segment[][] {
    const endsOf = (bundle: Segment[]): LaneEnds => {
        const representative = [...bundle].sort(
            (first, second) => compareIds(paths[first.path].id, paths[second.path].id) || first.index - second.index
        )[0];
        const { points, id } = paths[representative.path];
        const along: Axis = axis === 'x' ? 'y' : 'x';
        const start = points[representative.index];
        const end = points[representative.index + 1];
        const sideBefore = Math.sign(points[representative.index - 1][axis] - representative.line);
        const sideAfter = Math.sign(points[representative.index + 2][axis] - representative.line);
        const startIsLow = start[along] < end[along];
        const stubBefore = representative.index - 1 === 0;
        const stubAfter = representative.index + 1 === points.length - 2;
        return {
            id,
            low: representative.low,
            high: representative.high,
            lowSide: startIsLow ? sideBefore : sideAfter,
            highSide: startIsLow ? sideAfter : sideBefore,
            lowIsStub: startIsLow ? stubBefore : stubAfter,
            highIsStub: startIsLow ? stubAfter : stubBefore,
        };
    };
    const withEnds = bundles.map((bundle) => ({ bundle, ends: endsOf(bundle) }));
    withEnds.sort((first, second) => compareIds(first.ends.id, second.ends.id));
    withEnds.sort((first, second) => compareLanes(first.ends, second.ends));
    return withEnds.map(({ bundle }) => bundle);
}

/**
 * Negative when lane `a` belongs on the lower coordinate side of `b`. At each end of the shared run,
 * the wire that leaves the run first leaves towards its side, so it must be on that side of the
 * other; the wire that runs on is indifferent. When the two ends disagree, one of them has to be
 * lost. Losing an end where both wires leave at the same coordinate puts their two legs on one
 * line, on top of each other; losing any other end costs a crossing, on the leg the first wire
 * leaves by. So an end shared by both decides over one that isn't; then an end left by a stub (a
 * crossed stub reads as a wire into the wrong port, and the risers of stacked sources nest);
 * otherwise the low end decides. When neither end decides, the id does.
 */
function compareLanes(a: LaneEnds, b: LaneEnds): number {
    const atLow = a.low === b.low ? Math.sign(a.lowSide - b.lowSide) : a.low > b.low ? a.lowSide : -b.lowSide;
    const atHigh = a.high === b.high ? Math.sign(a.highSide - b.highSide) : a.high < b.high ? a.highSide : -b.highSide;
    const endsDisagree = atLow !== 0 && atHigh !== 0 && atLow !== atHigh;
    if (endsDisagree && a.low !== b.low) {
        if (a.high === b.high) return atHigh;
        const stubLeavesAtLow = a.low > b.low ? a.lowIsStub : b.lowIsStub;
        const stubLeavesAtHigh = a.high < b.high ? a.highIsStub : b.highIsStub;
        if (stubLeavesAtHigh && !stubLeavesAtLow) return atHigh;
    }
    return atLow || atHigh || compareIds(a.id, b.id);
}

function placeLanes(
    paths: RoutedPath[],
    firstFixed: number,
    lines: SegmentLines,
    orderedLanes: Segment[][],
    obstacles: Rect[],
    axis: Axis
): void {
    const isFixedLane = (lane: Segment[]): boolean => lane.some((segment) => segment.path >= firstFixed);
    const fixedLaneCount = orderedLanes.filter(isFixedLane).length;
    // Deliberate limit: with two hand-edited wires on one line the group stays as drawn, the others included.
    if (fixedLaneCount > 1) return;
    // The crossing-free order may put a lane on a side where it has no room (a fixed lane pins the
    // layout to its line; a lane between two touching padded boxes can't move at all), so the
    // reversed order is the fallback: a crossing where the wires part beats running on top of each other.
    const orders = [orderedLanes, [...orderedLanes].reverse()];
    for (const lanes of orders) {
        if (tryPlaceLanes(paths, lines, lanes, lanes.findIndex(isFixedLane), obstacles, axis)) return;
    }
}

// Lays the lanes out centred on their line, or anchored on the fixed lane (index `fixedLane`, −1
// for none); true when a placement was kept.
function tryPlaceLanes(
    paths: RoutedPath[],
    lines: SegmentLines,
    lanes: Segment[][],
    fixedLane: number,
    obstacles: Rect[],
    axis: Axis
): boolean {
    const segments = lanes.flat();
    const lineOfLane = (lane: Segment[]): number => lane[0].line;
    const centre = (lineOfLane(lanes[0]) + lineOfLane(lanes[lanes.length - 1])) / 2;
    const low = Math.min(...segments.map((segment) => segment.low));
    const high = Math.max(...segments.map((segment) => segment.high));
    const channel = freeChannel(obstacles, axis, centre, low, high);
    // Each lane is bounded by the obstacles beside its own extent: a short lane below a node's
    // bottom may pass where a long one would enter it.
    const limitsOf = (lane: Segment[]): { min: number; max: number } => {
        const line = lineOfLane(lane);
        const own = freeChannel(
            obstacles,
            axis,
            line,
            Math.min(...lane.map((segment) => segment.low)),
            Math.max(...lane.map((segment) => segment.high))
        );
        return { min: line - own.below, max: line + own.above };
    };
    const bounds = lanes.map((lane, laneIndex) =>
        laneIndex === fixedLane
            ? { min: lineOfLane(lane), max: lineOfLane(lane) }
            : laneBounds(paths, lines, lane, axis, limitsOf(lane))
    );

    // The moved segments and the neighbours they stretch: where a move can add or remove overlaps.
    const affected = segments.flatMap((segment) =>
        [segment.index - 1, segment.index, segment.index + 1].map((index) => ({ path: segment.path, index }))
    );
    const conflictsBefore = conflictsAround(paths, lines, affected);
    const original = segments.map((segment) => paths[segment.path].points[segment.index][axis]);
    const moveTo = (positionOf: (segment: Segment, segmentIndex: number) => number): void =>
        segments.forEach((segment, segmentIndex) => {
            const { points } = paths[segment.path];
            lines.remove(segment.path, segment.index);
            points[segment.index][axis] = positionOf(segment, segmentIndex);
            points[segment.index + 1][axis] = positionOf(segment, segmentIndex);
            lines.insert(segment.path, segment.index);
        });
    const laneOf = new Map(lanes.flatMap((lane, laneIndex) => lane.map((segment) => [segment, laneIndex] as const)));

    // A group whose shared channel has no width (one lane between two touching padded boxes) has
    // nothing to centre in: the lanes' own limits decide, from the full spacing down.
    const room = channel.below + channel.above;
    let spacing = room > 0 ? Math.min(LANE_SPACING, room / (lanes.length + 1)) : LANE_SPACING;
    for (let attempt = 0; attempt < SPACING_ATTEMPTS && spacing > 0; attempt++, spacing /= 2) {
        const anchor = fixedLane >= 0 ? fixedLane : (lanes.length - 1) / 2;
        const anchorLine = fixedLane >= 0 ? lineOfLane(lanes[fixedLane]) : centre;
        const positions = lanes.map((_, laneIndex) => anchorLine + (laneIndex - anchor) * spacing);
        const minimumShift = Math.max(...positions.map((position, laneIndex) => bounds[laneIndex].min - position));
        const maximumShift = Math.min(...positions.map((position, laneIndex) => bounds[laneIndex].max - position));
        if (minimumShift > maximumShift) continue;
        const shift = Math.min(Math.max(0, minimumShift), maximumShift);
        moveTo((segment) => positions[laneOf.get(segment)!] + shift);
        // Keep the lanes only if they leave fewer conflicts than before: a lane must not land on,
        // or next to, or stretch a neighbour onto, another wire.
        if (conflictsAround(paths, lines, affected) < conflictsBefore) return true;
        moveTo((_, segmentIndex) => original[segmentIndex]);
    }
    return false;
}

/**
 * Conflicts between the given segments and parallel segments of other wires they share no port
 * with, stubs included: a collinear overlap (> 1 px on one pixel row) weighs COLLINEAR_WEIGHT; a
 * pair closer than a lane side by side (NEAR_OVERLAP), or collinear end to end (END_TO_END_GAP),
 * weighs 1. A pair seen from both sides counts twice.
 */
function conflictsAround(
    paths: RoutedPath[],
    lines: SegmentLines,
    segments: { path: number; index: number }[]
): number {
    let score = 0;
    for (const { path, index } of segments) {
        const line = lineOf(paths, path, index);
        if (!line) continue;
        const { axis, position, low, high } = line;
        for (const other of lines.within(axis, position, NEAR_DISTANCE)) {
            if (other.path === path || sharesPort(paths[path], paths[other.path])) continue;
            const otherLine = lineOf(paths, other.path, other.index);
            if (!otherLine || otherLine.axis !== axis) continue;
            const distance = Math.abs(otherLine.position - position);
            if (distance >= NEAR_DISTANCE) continue;
            const overlap = Math.min(high, otherLine.high) - Math.max(low, otherLine.low);
            if (distance < SAME_LINE_TOLERANCE) {
                if (overlap > MIN_SEGMENT) score += COLLINEAR_WEIGHT;
                else if (overlap >= -END_TO_END_GAP) score++;
            } else if (overlap > NEAR_OVERLAP) {
                score++;
            }
        }
    }
    return score;
}

interface SegmentLine {
    axis: Axis; // 'x': a vertical segment, at x = position
    position: number;
    low: number; // its extent along the line
    high: number;
}

function lineOf(paths: RoutedPath[], path: number, index: number): SegmentLine | null {
    const { points } = paths[path];
    if (index < 0 || index >= points.length - 1) return null;
    const start = points[index];
    const end = points[index + 1];
    if (start.x === end.x && start.y !== end.y) {
        return { axis: 'x', position: start.x, low: Math.min(start.y, end.y), high: Math.max(start.y, end.y) };
    }
    if (start.y === end.y && start.x !== end.x) {
        return { axis: 'y', position: start.y, low: Math.min(start.x, end.x), high: Math.max(start.x, end.x) };
    }
    return null;
}

/**
 * Every segment of every path, bucketed by the line it lies on (SAME_LINE_TOLERANCE-wide
 * buckets), so finding what shares a line doesn't scan all wires. Callers keep it current by
 * removing a segment before moving it and inserting it after.
 */
class SegmentLines {
    private readonly buckets = new Map<string, { path: number; index: number }[]>();

    constructor(private readonly paths: RoutedPath[]) {
        paths.forEach((routed, path) => routed.points.slice(1).forEach((_, index) => this.insert(path, index)));
    }

    insert(path: number, index: number): void {
        const line = lineOf(this.paths, path, index);
        if (!line) return;
        const key = bucketKey(line.axis, line.position);
        const bucket = this.buckets.get(key);
        if (bucket) bucket.push({ path, index });
        else this.buckets.set(key, [{ path, index }]);
    }

    remove(path: number, index: number): void {
        const line = lineOf(this.paths, path, index);
        if (!line) return;
        const bucket = this.buckets.get(bucketKey(line.axis, line.position));
        const position = bucket?.findIndex((entry) => entry.path === path && entry.index === index) ?? -1;
        if (position >= 0) bucket!.splice(position, 1);
    }

    /** Segments on the axis within `distance` of `position`, give or take a bucket (callers check the exact distance). */
    within(axis: Axis, position: number, distance: number): { path: number; index: number }[] {
        const first = Math.floor((position - distance) / SAME_LINE_TOLERANCE) - 1;
        const last = Math.floor((position + distance) / SAME_LINE_TOLERANCE) + 1;
        const result: { path: number; index: number }[] = [];
        for (let bucket = first; bucket <= last; bucket++) result.push(...(this.buckets.get(`${axis}${bucket}`) ?? []));
        return result;
    }
}

function bucketKey(axis: Axis, position: number): string {
    return `${axis}${Math.floor(position / SAME_LINE_TOLERANCE)}`;
}

// Free space on each side of the line up to the nearest obstacle beside the run [low, high].
function freeChannel(
    obstacles: Rect[],
    axis: Axis,
    line: number,
    low: number,
    high: number
): { below: number; above: number } {
    let below = Number.POSITIVE_INFINITY;
    let above = Number.POSITIVE_INFINITY;
    for (const obstacle of obstacles) {
        const [start, end, alongStart, alongEnd] =
            axis === 'x'
                ? [obstacle.left, obstacle.right, obstacle.top, obstacle.bottom]
                : [obstacle.top, obstacle.bottom, obstacle.left, obstacle.right];
        if (alongEnd <= low || alongStart >= high) continue;
        if (end <= line) below = Math.min(below, line - end);
        else if (start >= line) above = Math.min(above, start - line);
    }
    return { below, above };
}

// Where a lane may go: inside the channel limits, never flipping a neighbouring segment, keeping
// the stubs at least STUB long, and never stretching a neighbour onto another wire's first or last
// segment on its line (those never move, so the overlap would stay).
function laneBounds(
    paths: RoutedPath[],
    lines: SegmentLines,
    lane: Segment[],
    axis: Axis,
    limits: { min: number; max: number }
): { min: number; max: number } {
    const along: Axis = axis === 'x' ? 'y' : 'x';
    const line = lane[0].line;
    let { min, max } = limits;
    for (const segment of lane) {
        const { points } = paths[segment.path];
        const lastSegment = points.length - 2;
        const neighbours: [number, boolean, number][] = [
            [points[segment.index - 1][axis], segment.index - 1 === 0, points[segment.index][along]],
            [points[segment.index + 2][axis], segment.index + 1 === lastSegment, points[segment.index + 1][along]],
        ];
        for (const [farEnd, isStub, neighbourLine] of neighbours) {
            const margin = isStub ? STUB : MIN_SEGMENT;
            if (farEnd < line) min = Math.max(min, farEnd + margin);
            else if (farEnd > line) max = Math.min(max, farEnd - margin);
            for (const pinned of pinnedSegmentsOn(paths, lines, along, neighbourLine, segment.path)) {
                if (farEnd < line && pinned.low >= line) max = Math.min(max, pinned.low);
                else if (farEnd > line && pinned.high <= line) min = Math.max(min, pinned.high);
            }
        }
    }
    return { min, max };
}

// First and last segments of other wires (sharing no port with `path`) on the line at `position`.
function pinnedSegmentsOn(
    paths: RoutedPath[],
    lines: SegmentLines,
    axis: Axis,
    position: number,
    path: number
): SegmentLine[] {
    const result: SegmentLine[] = [];
    for (const other of lines.within(axis, position, SAME_LINE_TOLERANCE)) {
        if (other.path === path || sharesPort(paths[path], paths[other.path])) continue;
        if (other.index !== 0 && other.index !== paths[other.path].points.length - 2) continue;
        const otherLine = lineOf(paths, other.path, other.index);
        if (otherLine?.axis === axis && Math.abs(otherLine.position - position) < SAME_LINE_TOLERANCE) {
            result.push(otherLine);
        }
    }
    return result;
}

function compareIds(first: string, second: string): number {
    return first < second ? -1 : first > second ? 1 : 0;
}
