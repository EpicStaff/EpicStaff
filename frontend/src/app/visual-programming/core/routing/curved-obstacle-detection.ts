import { IPoint } from '@foblex/2d';

import {
    computeBackwardLoopGeometry,
    computeBackwardSCurveGeometry,
    CURVED_STRAIGHT_LINE_THRESHOLD,
    CURVED_STUB,
    MAX_OFFSET,
    MIN_OFFSET,
    OFFSET_RATIO,
} from './curved-geometry';
import { Rect } from './obstacles';
import { clamp, isWithinStraightLineThreshold } from './path-builder-shared';

// Higher values produce smoother obstacle-detection sampling at the cost of more
// point-in-rect checks per connection. 16/8 keep re-routing under 1 ms on large graphs.
const BEZIER_SAMPLES = 16;
const ARC_SAMPLES = 8;

/**
 * Returns true when the smooth curve that `CurvedPathBuilder` would draw between
 * `source` and `target` passes through at least one obstacle rect.
 *
 * Call this **before** setting waypoints on the connection: the caller decides
 * whether to keep A* waypoints (curve hits obstacle) or clear them (curve is free).
 */
export function curveHitsObstacle(source: IPoint, target: IPoint, obstacles: Rect[]): boolean {
    if (obstacles.length === 0) return false;
    if (isWithinStraightLineThreshold(source, target, CURVED_STRAIGHT_LINE_THRESHOLD)) {
        const relevantObstacles = excludeEndpointObstacles(obstacles, source, target);
        return relevantObstacles.length > 0 && pathHitsObstacle([source, target], relevantObstacles);
    }
    const exitX = source.x + CURVED_STUB;
    const entryX = target.x - CURVED_STUB;
    const samplePoints =
        entryX <= exitX
            ? backwardCurveSamplePoints(source, target, exitX, entryX)
            : forwardCurveSamplePoints(source, target, exitX, entryX);
    // Check the interior curve against all obstacles (including endpoint nodes).
    // The first and last sample points (exit/entry) may sit inside their own node's
    // padded rect, so exclude endpoint obstacles only for those two edge segments.
    if (samplePoints.length < 3) return pathHitsObstacle(samplePoints, obstacles);
    const endpointFiltered = excludeEndpointObstacles(obstacles, source, target);
    return (
        pathHitsObstacle(samplePoints.slice(0, 2), endpointFiltered) ||
        pathHitsObstacle(samplePoints.slice(1, -1), obstacles) ||
        pathHitsObstacle(samplePoints.slice(-2), endpointFiltered)
    );
}

// ── Curve sampling ──────────────────────────────────────────────────────────
//
// These functions sample only the stub-to-stub curve (exitPoint → entryPoint),
// excluding the horizontal stubs inside the endpoint nodes. This lets
// curveHitsObstacle check against ALL obstacle rects — including the source and
// target nodes — without false positives from the stubs.

function forwardCurveSamplePoints(source: IPoint, target: IPoint, exitX: number, entryX: number): IPoint[] {
    const gap = entryX - exitX;
    const offset = clamp(gap * OFFSET_RATIO, MIN_OFFSET, MAX_OFFSET);
    return sampleCubicBezier(
        { x: exitX, y: source.y },
        { x: exitX + offset, y: source.y },
        { x: entryX - offset, y: target.y },
        { x: entryX, y: target.y },
        BEZIER_SAMPLES
    );
}

function backwardCurveSamplePoints(source: IPoint, target: IPoint, exitX: number, entryX: number): IPoint[] {
    const verticalGap = source.y - target.y;
    if (Math.abs(verticalGap) < CURVED_STUB) {
        return backwardLoopCurveSamplePoints(source, target, exitX, entryX);
    }
    return backwardSCurveSamplePoints(source, target, exitX, entryX, verticalGap);
}

function backwardSCurveSamplePoints(
    source: IPoint,
    target: IPoint,
    exitX: number,
    entryX: number,
    verticalGap: number
): IPoint[] {
    const geometry = computeBackwardSCurveGeometry(source, target, exitX, entryX, verticalGap);
    if (!geometry) {
        return backwardLoopCurveSamplePoints(source, target, exitX, entryX);
    }

    const { radius, exitCircleY, entryCircleY, tangentExitPoint, tangentEntryPoint, contactAngle } = geometry;
    const sign = verticalGap >= 0 ? 1 : -1;

    if (sign * (tangentExitPoint.y - tangentEntryPoint.y) <= 0) {
        return backwardLoopCurveSamplePoints(source, target, exitX, entryX);
    }

    const exitCenter: IPoint = { x: exitX, y: exitCircleY };
    const entryCenter: IPoint = { x: entryX, y: entryCircleY };

    const exitSweep = sign > 0 ? 0 : 1;
    const exitArcStart = sign * (Math.PI / 2);
    const exitArcEnd = contactAngle;
    const entryArcStart = Math.PI + contactAngle;
    const entryArcEnd = -sign * (Math.PI / 2);

    return [
        ...sampleArc(exitCenter, radius, exitArcStart, exitArcEnd, exitSweep, ARC_SAMPLES),
        tangentExitPoint,
        tangentEntryPoint,
        ...sampleArc(entryCenter, radius, entryArcStart, entryArcEnd, 1 - exitSweep, ARC_SAMPLES),
    ];
}

function backwardLoopCurveSamplePoints(source: IPoint, target: IPoint, exitX: number, entryX: number): IPoint[] {
    const { radius, topY } = computeBackwardLoopGeometry(source, target, exitX, entryX);

    const c1: IPoint = { x: exitX + radius, y: source.y - radius };
    const c2: IPoint = { x: exitX, y: topY + radius };
    const c3: IPoint = { x: entryX, y: topY + radius };
    const c4: IPoint = { x: entryX - radius, y: target.y - radius };

    return [
        ...sampleArc(c1, radius, Math.PI / 2, 0, 0, ARC_SAMPLES),
        ...sampleArc(c2, radius, 0, -Math.PI / 2, 0, ARC_SAMPLES),
        ...sampleArc(c3, radius, -Math.PI / 2, -Math.PI, 0, ARC_SAMPLES),
        ...sampleArc(c4, radius, -Math.PI, -Math.PI * 1.5, 0, ARC_SAMPLES),
    ];
}

// ── Helpers ────────────────────────────────────────────────────────────────────

/** Evenly spaced points along a cubic Bézier (t = 0 … 1 inclusive). */
function sampleCubicBezier(p0: IPoint, p1: IPoint, p2: IPoint, p3: IPoint, count: number): IPoint[] {
    const points: IPoint[] = [];
    for (let index = 0; index <= count; index++) {
        const t = index / count;
        const u = 1 - t;
        const u2 = u * u;
        const t2 = t * t;
        points.push({
            x: u2 * u * p0.x + 3 * u2 * t * p1.x + 3 * u * t2 * p2.x + t2 * t * p3.x,
            y: u2 * u * p0.y + 3 * u2 * t * p1.y + 3 * u * t2 * p2.y + t2 * t * p3.y,
        });
    }
    return points;
}

/** Evenly spaced points along a circular arc (excluding endpoints). */
function sampleArc(
    center: IPoint,
    radius: number,
    startAngle: number,
    endAngle: number,
    sweep: number,
    count: number
): IPoint[] {
    const TAU = 2 * Math.PI;
    let span = endAngle - startAngle;
    // Normalize span to match sweep direction: sweep=0 (CCW) → negative, sweep=1 (CW) → positive
    if (sweep === 0 && span > 0) span -= TAU;
    if (sweep === 1 && span < 0) span += TAU;

    const points: IPoint[] = [];
    for (let index = 1; index < count; index++) {
        const t = index / count;
        const angle = startAngle + span * t;
        points.push({
            x: center.x + radius * Math.cos(angle),
            y: center.y + radius * Math.sin(angle),
        });
    }
    return points;
}

/** Obstacles that contain a port point belong to the source/target nodes — skip them. */
function excludeEndpointObstacles(obstacles: Rect[], source: IPoint, target: IPoint): Rect[] {
    return obstacles.filter((rect) => !pointInsideRect(source, rect) && !pointInsideRect(target, rect));
}

function pointInsideRect(point: IPoint, rect: Rect): boolean {
    return point.x >= rect.left && point.x <= rect.right && point.y >= rect.top && point.y <= rect.bottom;
}

/** True when any line segment between consecutive points crosses an obstacle rect. */
function pathHitsObstacle(points: IPoint[], obstacles: Rect[]): boolean {
    for (let index = 0; index < points.length - 1; index++) {
        for (const rect of obstacles) {
            if (segmentIntersectsRect(points[index], points[index + 1], rect)) {
                return true;
            }
        }
    }
    return false;
}

/**
 * Cohen–Sutherland line-segment vs axis-aligned-rect intersection.
 * Returns true when any part of the segment [p1, p2] overlaps the rect.
 */
function segmentIntersectsRect(p1: IPoint, p2: IPoint, rect: Rect): boolean {
    let x0 = p1.x,
        y0 = p1.y,
        x1 = p2.x,
        y1 = p2.y;
    let code0 = outCode(x0, y0, rect);
    let code1 = outCode(x1, y1, rect);

    while (true) {
        if ((code0 | code1) === 0) return true;
        if ((code0 & code1) !== 0) return false;

        const codeOut = code0 !== 0 ? code0 : code1;
        let x: number, y: number;

        if (codeOut & 8) {
            x = x0 + ((x1 - x0) * (rect.bottom - y0)) / (y1 - y0);
            y = rect.bottom;
        } else if (codeOut & 4) {
            x = x0 + ((x1 - x0) * (rect.top - y0)) / (y1 - y0);
            y = rect.top;
        } else if (codeOut & 2) {
            y = y0 + ((y1 - y0) * (rect.right - x0)) / (x1 - x0);
            x = rect.right;
        } else {
            y = y0 + ((y1 - y0) * (rect.left - x0)) / (x1 - x0);
            x = rect.left;
        }

        if (codeOut === code0) {
            x0 = x;
            y0 = y;
            code0 = outCode(x0, y0, rect);
        } else {
            x1 = x;
            y1 = y;
            code1 = outCode(x1, y1, rect);
        }
    }
}

function outCode(x: number, y: number, rect: Rect): number {
    let code = 0;
    if (x < rect.left) code |= 1;
    else if (x > rect.right) code |= 2;
    if (y < rect.top) code |= 4;
    else if (y > rect.bottom) code |= 8;
    return code;
}
