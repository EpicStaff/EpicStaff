import { IPoint } from '@foblex/2d';

/** The stub: the first/last STUB px of a wire, from the port to the search's start/goal. */
export const STUB = 20;

/**
 * An interior segment shorter than this reads as a kink. The search and jog-cleanup both use
 * this threshold to penalise or remove short interior segments.
 */
export const MIN_INTERIOR_SEGMENT = 10;

/**
 * Sub-pixel tolerance: segments closer than this are on the same pixel row. Used by the quality
 * checker and by short-segment detection (a 9.5-px segment is not short).
 */
export const LENGTH_TOLERANCE = 0.5;

/**
 * The signed overlap of two 1-D ranges [low1, high1] and [low2, high2]. Positive when they
 * overlap, zero when they touch, negative when they are apart (the gap's width, negated).
 */
export function rangeOverlap(low1: number, high1: number, low2: number, high2: number): number {
    return Math.min(high1, high2) - Math.max(low1, low2);
}

/**
 * Whether two routed paths share a source or target port, by their string port keys. Wires
 * sharing a port are a "trunk" and tolerate collinear overlap (nudging keeps them together).
 */
export function sharesPort(
    first: { sourcePortKey: string; targetPortKey: string },
    second: { sourcePortKey: string; targetPortKey: string }
): boolean {
    return first.sourcePortKey === second.sourcePortKey || first.targetPortKey === second.targetPortKey;
}

/**
 * An axis-parallel piece of a polyline, used by jog-cleanup, nudging, and the quality checker.
 */
export interface AxisSegment {
    horizontal: boolean;
    line: number; // y of a horizontal segment, x of a vertical one
    low: number; // its extent along the line
    high: number;
}

/**
 * Calls `visit` for each axis-parallel piece of a polyline, with the index of the point pair it
 * belongs to; a diagonal pair (possible in hand-made waypoints) counts as horizontal-then-vertical.
 * Zero-length pieces are skipped.
 */
export function forEachAxisSegment(
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

/**
 * Builds an array of axis-parallel segments from a polyline. Diagonal pairs are skipped (only
 * pure horizontal or vertical segments are returned). Use `forEachAxisSegment` when diagonal
 * decomposition or the pair index is needed.
 */
export function axisSegments(points: IPoint[]): AxisSegment[] {
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

/**
 * Drops repeated points and points in the middle of a straight run; returns null when the path
 * doubles back on itself (a reversal). Handles both collinear removal and reversal detection,
 * making it a strict superset of plain collinear removal.
 */
export function simplified(points: IPoint[]): IPoint[] | null {
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
