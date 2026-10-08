import { IPoint } from '@foblex/2d';

import { Rect, WIRE_CLEARANCE } from './obstacles';

/**
 * Pure functions for building smooth SVG curves using Catmull-Rom spline
 * interpolation, converted to cubic Bezier segments for SVG path output.
 */

/**
 * Given N points (N >= 2), generate a smooth SVG path using Catmull-Rom to
 * cubic Bezier conversion.
 *
 * For Catmull-Rom: given four consecutive points P0, P1, P2, P3, the Bezier
 * control points for the segment P1 -> P2 are:
 *   cp1 = P1 + (P2 - P0) / 6
 *   cp2 = P2 - (P3 - P1) / 6
 *
 * Boundary handling: the first point is duplicated as the phantom before the
 * start, and the last point is duplicated as the phantom after the end.
 *
 * The path uses only M and C commands — no L commands (which create visible
 * kinks at joins).
 */
export function buildCatmullRomPath(points: IPoint[]): string {
    if (points.length < 2) {
        return '';
    }

    if (points.length === 2) {
        return buildTwoPointCurve(points[0], points[1]);
    }

    const first = points[0];
    let path = `M ${first.x} ${first.y}`;

    for (let index = 0; index < points.length - 1; index++) {
        const previous = index > 0 ? points[index - 1] : points[0];
        const current = points[index];
        const next = points[index + 1];
        const afterNext = index + 2 < points.length ? points[index + 2] : points[points.length - 1];

        const controlPoint1: IPoint = {
            x: current.x + (next.x - previous.x) / 6,
            y: current.y + (next.y - previous.y) / 6,
        };

        const controlPoint2: IPoint = {
            x: next.x - (afterNext.x - current.x) / 6,
            y: next.y - (afterNext.y - current.y) / 6,
        };

        path += ` C ${controlPoint1.x} ${controlPoint1.y}, ${controlPoint2.x} ${controlPoint2.y}, ${next.x} ${next.y}`;
    }

    return path;
}

/**
 * For a direct forward connection (no obstacles). Returns intermediate
 * through-points that make the curve exit source heading east and enter
 * target heading west.
 */
export function computeForwardControlPoints(source: IPoint, target: IPoint): IPoint[] {
    const MAX_OFFSET = 200;
    const OFFSET_RATIO = 0.4;

    const horizontalDistance = Math.abs(target.x - source.x);
    // Cap offset to 40% of the distance, but never more than half the distance
    // (prevents through-points from crossing on short connections).
    const offset = Math.min(horizontalDistance * OFFSET_RATIO, horizontalDistance / 2, MAX_OFFSET);

    // Blend Y values so Catmull-Rom through-points guide the curve directly
    // toward the target instead of staying flat at source/target Y (which
    // causes overshoot S-loops when there is a vertical difference).
    const deltaY = target.y - source.y;

    // When the path is nearly horizontal (deltaY ≈ 0), the SVG bounding box
    // has zero height which breaks objectBoundingBox gradient rendering in
    // Foblex. Add a subtle vertical arc (1px) to prevent this.
    const MINIMUM_VERTICAL_OFFSET = 1;
    const verticalArc = Math.abs(deltaY) < MINIMUM_VERTICAL_OFFSET * 2 ? MINIMUM_VERTICAL_OFFSET : 0;

    return [
        { x: source.x + offset, y: source.y + deltaY * 0.25 - verticalArc },
        { x: target.x - offset, y: source.y + deltaY * 0.75 + verticalArc },
    ];
}

/**
 * For backward connections (target.x < source.x). The curve must loop
 * around: exit source eastward, arc above (or below) both nodes, enter
 * target from the west.
 *
 * When obstacle rects are provided they determine clearance; otherwise a
 * default clearance is applied from the port positions.
 */
export function computeBackwardControlPoints(
    source: IPoint,
    target: IPoint,
    sourceObstacle: Rect | null,
    targetObstacle: Rect | null
): IPoint[] {
    const STUB_LENGTH = 40;
    const DEFAULT_VERTICAL_CLEARANCE = WIRE_CLEARANCE * 4;

    const exitStub: IPoint = { x: source.x + STUB_LENGTH, y: source.y };
    const entryStub: IPoint = { x: target.x - STUB_LENGTH, y: target.y };

    // Determine the top edge to clear — prefer going above
    const sourceTop = sourceObstacle ? sourceObstacle.top : source.y - DEFAULT_VERTICAL_CLEARANCE;
    const targetTop = targetObstacle ? targetObstacle.top : target.y - DEFAULT_VERTICAL_CLEARANCE;
    const clearanceY = Math.min(sourceTop, targetTop) - DEFAULT_VERTICAL_CLEARANCE;

    const topRight: IPoint = { x: exitStub.x, y: clearanceY };
    const topLeft: IPoint = { x: entryStub.x, y: clearanceY };

    return [exitStub, topRight, topLeft, entryStub];
}

// --- Internal helpers ---

function buildTwoPointCurve(source: IPoint, target: IPoint): string {
    // For a direct 2-point Bezier, control points stay at source.y / target.y
    // to produce a horizontal exit and horizontal entry. This differs from
    // computeForwardControlPoints() which blends Y for Catmull-Rom through-points.
    const MIN_OFFSET = 50;
    const MAX_OFFSET = 200;
    const OFFSET_RATIO = 0.4;

    const offset = clamp(Math.abs(target.x - source.x) * OFFSET_RATIO, MIN_OFFSET, MAX_OFFSET);
    const controlPoint1: IPoint = { x: source.x + offset, y: source.y };
    const controlPoint2: IPoint = { x: target.x - offset, y: target.y };

    return (
        `M ${source.x} ${source.y}` +
        ` C ${controlPoint1.x} ${controlPoint1.y}, ${controlPoint2.x} ${controlPoint2.y}, ${target.x} ${target.y}`
    );
}

function clamp(value: number, minimum: number, maximum: number): number {
    return Math.max(minimum, Math.min(maximum, value));
}
