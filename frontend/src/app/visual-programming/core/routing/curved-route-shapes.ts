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
// Maximum distance a Bezier control point can sit from its anchor.
// Prevents overshooting arcs when Catmull-Rom tangent vectors are very long
// (e.g., backward loops where the top horizontal span is large).
const MAX_TANGENT = 50;

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

        let tangent1X = (next.x - previous.x) / 6;
        let tangent1Y = (next.y - previous.y) / 6;
        let tangent2X = (afterNext.x - current.x) / 6;
        let tangent2Y = (afterNext.y - current.y) / 6;

        const length1 = Math.sqrt(tangent1X * tangent1X + tangent1Y * tangent1Y);
        if (length1 > MAX_TANGENT) {
            const scale = MAX_TANGENT / length1;
            tangent1X *= scale;
            tangent1Y *= scale;
        }

        const length2 = Math.sqrt(tangent2X * tangent2X + tangent2Y * tangent2Y);
        if (length2 > MAX_TANGENT) {
            const scale = MAX_TANGENT / length2;
            tangent2X *= scale;
            tangent2Y *= scale;
        }

        const controlPoint1: IPoint = {
            x: current.x + tangent1X,
            y: current.y + tangent1Y,
        };

        const controlPoint2: IPoint = {
            x: next.x - tangent2X,
            y: next.y - tangent2Y,
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

    // Stubs must clear both node bodies to prevent Catmull-Rom swing-through
    const exitStubX =
        sourceObstacle && targetObstacle
            ? Math.max(
                  source.x + STUB_LENGTH,
                  sourceObstacle.right + WIRE_CLEARANCE,
                  targetObstacle.right + WIRE_CLEARANCE
              )
            : source.x + STUB_LENGTH;
    const entryStubX =
        sourceObstacle && targetObstacle
            ? Math.min(
                  target.x - STUB_LENGTH,
                  sourceObstacle.left - WIRE_CLEARANCE,
                  targetObstacle.left - WIRE_CLEARANCE
              )
            : target.x - STUB_LENGTH;

    // Always loop above — matches orthogonal router behaviour.
    const sourceTop = sourceObstacle ? sourceObstacle.top : source.y - DEFAULT_VERTICAL_CLEARANCE;
    const targetTop = targetObstacle ? targetObstacle.top : target.y - DEFAULT_VERTICAL_CLEARANCE;
    const clearanceY = Math.min(sourceTop, targetTop) - DEFAULT_VERTICAL_CLEARANCE;

    // Offset stub Y slightly toward clearanceY so the Catmull-Rom tangent
    // at the stub already points toward the loop, preventing "knee" dips.
    const STUB_Y_BLEND = 0.15;
    const exitStubY = source.y + (clearanceY - source.y) * STUB_Y_BLEND;
    const entryStubY = target.y + (clearanceY - target.y) * STUB_Y_BLEND;

    return [
        { x: exitStubX, y: exitStubY },
        { x: exitStubX, y: clearanceY },
        { x: entryStubX, y: clearanceY },
        { x: entryStubX, y: entryStubY },
    ];
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
