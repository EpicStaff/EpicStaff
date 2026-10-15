import { IPoint } from '@foblex/2d';

import { RoutedPath } from './nudging';
import { Rect } from './obstacles';

/**
 * Removes kinks: an interior segment shorter than 10 px between two parallel segments is
 * taken out by moving one of those two onto the other's line, or, when neither can go there,
 * widened to 10 px by moving one of them further away. The earlier neighbour is tried before the
 * later one, aligning before widening; a stub (the first or last segment) never moves. A move is kept only if the
 * wire stays out of every node, keeps its stubs, doesn't cross itself, has fewer short segments,
 * and gains no crossing and no overlap with any other wire. Otherwise the jog stays. Runs after
 * nudging; pure and deterministic (paths in their order, jogs from the source on).
 */

const MIN_INTERIOR_SEGMENT = 10;
const STUB = 20;
// Sub-pixel tolerance, as the quality checker uses: closer than this is the same pixel row.
const EPSILON = 0.5;
// A collinear run longer than this on top of another wire is an overlap.
const MIN_OVERLAP = 1;

interface AxisSegment {
    horizontal: boolean;
    line: number; // y of a horizontal segment, x of a vertical one
    low: number; // its extent along the line
    high: number;
}

/**
 * `paths` with their jogs removed where that is safe; same ids, same order. `others` (e.g. frozen
 * hand-made wires) are never changed but count for crossings and overlaps.
 */
export function removeJogs(paths: RoutedPath[], obstacles: Rect[], others: RoutedPath[] = []): RoutedPath[] {
    const working = paths.map((routed) => ({ ...routed, points: routed.points.map((point) => ({ ...point })) }));
    working.forEach((routed, pathIndex) => {
        let points = routed.points;
        for (let index = 1; index < points.length - 2; index++) {
            if (length(points[index], points[index + 1]) >= MIN_INTERIOR_SEGMENT - EPSILON) continue;
            const context = [...working.filter((_, otherIndex) => otherIndex !== pathIndex), ...others];
            const straightened = straightenJog(routed, points, index, obstacles, context);
            if (!straightened) continue;
            points = straightened;
            working[pathIndex] = { ...routed, points };
            index = 0; // the path changed: look again from the source
        }
    });
    return working;
}

function straightenJog(
    routed: RoutedPath,
    points: IPoint[],
    index: number,
    obstacles: Rect[],
    others: RoutedPath[]
): IPoint[] | null {
    const lastSegment = points.length - 2;
    // A vertical jog is removed by moving a horizontal neighbour in y, and vice versa.
    const axis: 'x' | 'y' = points[index].x === points[index + 1].x ? 'y' : 'x';
    const jogDirection = Math.sign(points[index + 1][axis] - points[index][axis]);
    const earlierMovable = index - 1 > 0;
    const laterMovable = index + 1 < lastSegment;
    const options: { segment: number; to: number }[] = [];
    if (earlierMovable) options.push({ segment: index - 1, to: points[index + 1][axis] });
    if (laterMovable) options.push({ segment: index + 1, to: points[index][axis] });
    if (earlierMovable) {
        options.push({ segment: index - 1, to: points[index + 1][axis] - jogDirection * MIN_INTERIOR_SEGMENT });
    }
    if (laterMovable) {
        options.push({ segment: index + 1, to: points[index][axis] + jogDirection * MIN_INTERIOR_SEGMENT });
    }

    for (const { segment, to } of options) {
        const moved = points.map((point) => ({ ...point }));
        moved[segment][axis] = to;
        moved[segment + 1][axis] = to;
        const candidate = simplified(moved);
        if (candidate && isAcceptable(routed, points, candidate, obstacles, others)) return candidate;
    }
    return null;
}

function isAcceptable(
    routed: RoutedPath,
    before: IPoint[],
    after: IPoint[],
    obstacles: Rect[],
    others: RoutedPath[]
): boolean {
    if (!hasStubs(after) || selfCrosses(after)) return false;
    if (shortSegmentCount(after) >= shortSegmentCount(before)) return false;
    if (entersObstacle(after, obstacles)) return false;
    const otherSegments = others.map((other) => ({ other, segments: axisSegments(other.points) }));
    const count = (points: IPoint[]): { crossings: number; overlaps: number } => {
        const own = axisSegments(points);
        let crossings = 0;
        let overlaps = 0;
        for (const { other, segments } of otherSegments) {
            const sharesPort =
                other.sourcePortKey === routed.sourcePortKey || other.targetPortKey === routed.targetPortKey;
            for (const segment of own) {
                for (const otherSegment of segments) {
                    if (crosses(segment, otherSegment)) crossings++;
                    else if (!sharesPort && overlapsCollinearly(segment, otherSegment)) overlaps++;
                }
            }
        }
        return { crossings, overlaps };
    };
    const original = count(before);
    const straightened = count(after);
    return straightened.crossings <= original.crossings && straightened.overlaps <= original.overlaps;
}

// Drops repeated points and points in the middle of a straight run; null when the path doubles back.
function simplified(points: IPoint[]): IPoint[] | null {
    const result: IPoint[] = [];
    for (const point of points) {
        const previous = result[result.length - 1];
        if (previous && previous.x === point.x && previous.y === point.y) continue;
        const beforePrevious = result[result.length - 2];
        if (beforePrevious) {
            const sameX = beforePrevious.x === previous.x && previous.x === point.x;
            const sameY = beforePrevious.y === previous.y && previous.y === point.y;
            if (sameX || sameY) {
                const axis = sameX ? 'y' : 'x';
                const reverses = (previous[axis] - beforePrevious[axis]) * (point[axis] - previous[axis]) < 0;
                if (reverses) return null;
                result.pop();
            }
        }
        result.push(point);
    }
    return result;
}

// The first segment leaves the source, the last enters the target, both east and at least STUB long.
function hasStubs(points: IPoint[]): boolean {
    const isStub = (start: IPoint, end: IPoint): boolean => start.y === end.y && end.x - start.x >= STUB - EPSILON;
    return (
        points.length >= 2 &&
        isStub(points[0], points[1]) &&
        isStub(points[points.length - 2], points[points.length - 1])
    );
}

function shortSegmentCount(points: IPoint[]): number {
    let count = 0;
    for (let index = 1; index < points.length - 2; index++) {
        if (length(points[index], points[index + 1]) < MIN_INTERIOR_SEGMENT - EPSILON) count++;
    }
    return count;
}

function selfCrosses(points: IPoint[]): boolean {
    const segments = axisSegments(points);
    for (let first = 0; first < segments.length; first++) {
        for (let second = first + 2; second < segments.length; second++) {
            if (crosses(segments[first], segments[second])) return true;
        }
    }
    return false;
}

// Any segment strictly inside a node's padded box. The stubs start inside their own node's box,
// so a box holding the stub's port point doesn't count for that stub.
function entersObstacle(points: IPoint[], obstacles: Rect[]): boolean {
    const lastSegment = points.length - 2;
    for (let index = 0; index <= lastSegment; index++) {
        const [start, end] = [points[index], points[index + 1]];
        const port = index === 0 ? start : index === lastSegment ? end : null;
        for (const box of obstacles) {
            if (port && port.x > box.left && port.x < box.right && port.y > box.top && port.y < box.bottom) continue;
            const enters =
                start.y === end.y
                    ? start.y > box.top &&
                      start.y < box.bottom &&
                      Math.max(Math.min(start.x, end.x), box.left) < Math.min(Math.max(start.x, end.x), box.right)
                    : start.x > box.left &&
                      start.x < box.right &&
                      Math.max(Math.min(start.y, end.y), box.top) < Math.min(Math.max(start.y, end.y), box.bottom);
            if (enters) return true;
        }
    }
    return false;
}

function axisSegments(points: IPoint[]): AxisSegment[] {
    const segments: AxisSegment[] = [];
    for (let index = 0; index < points.length - 1; index++) {
        const [start, end] = [points[index], points[index + 1]];
        if (start.y === end.y && start.x !== end.x) {
            segments.push({
                horizontal: true,
                line: start.y,
                low: Math.min(start.x, end.x),
                high: Math.max(start.x, end.x),
            });
        } else if (start.x === end.x && start.y !== end.y) {
            segments.push({
                horizontal: false,
                line: start.x,
                low: Math.min(start.y, end.y),
                high: Math.max(start.y, end.y),
            });
        }
    }
    return segments;
}

// A proper crossing: each strictly inside the other's extent (a T-junction or shared end doesn't count).
function crosses(first: AxisSegment, second: AxisSegment): boolean {
    if (first.horizontal === second.horizontal) return false;
    return first.low < second.line && second.line < first.high && second.low < first.line && first.line < second.high;
}

function overlapsCollinearly(first: AxisSegment, second: AxisSegment): boolean {
    if (first.horizontal !== second.horizontal || Math.abs(first.line - second.line) >= EPSILON) return false;
    return Math.min(first.high, second.high) - Math.max(first.low, second.low) > MIN_OVERLAP;
}

function length(start: IPoint, end: IPoint): number {
    return Math.abs(end.x - start.x) + Math.abs(end.y - start.y);
}
