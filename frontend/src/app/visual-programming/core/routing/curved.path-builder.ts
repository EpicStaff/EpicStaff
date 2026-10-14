import { IPoint } from '@foblex/2d';
import { IFConnectionBuilder, IFConnectionBuilderRequest, IFConnectionBuilderResponse } from '@foblex/flow';

import { Rect } from './obstacles';
import {
    buildRoundedOrthogonalPath,
    fallbackRoutePoints,
    normalizeOrthogonalWaypoints,
} from './orthogonal-route-shapes';

const STUB = 20;
const STRAIGHT_LINE_THRESHOLD = 60;
const MAX_ARC_RADIUS = 80;
const MIN_OFFSET = 20;
const MAX_OFFSET = 300;
const OFFSET_RATIO = 0.4;
const MIN_ARC_RADIUS = 15;
const ARC_RADIUS_RATIO = 0.12;
const LOOP_RADIUS_RATIO = 0.1;
const LOOP_MAX_RADIUS = 40;
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
    if (isWithinStraightLineThreshold(source, target)) {
        const relevantObstacles = excludeEndpointObstacles(obstacles, source, target);
        return relevantObstacles.length > 0 && pathHitsObstacle([source, target], relevantObstacles);
    }
    const exitX = source.x + STUB;
    const entryX = target.x - STUB;
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

/**
 * Foblex connection builder `'adaptive-curve'`: draws smooth cubic Bézier
 * curves with horizontal stubs at both ends.
 *
 * Forward connections (target right of source): stub → C curve → stub.
 * Backward with vertical gap: stub → arc → line → arc → stub (S-curve, both directions).
 * Backward without vertical gap: rounded-rectangle loop above both nodes.
 *
 * When waypoints are present the builder draws a rounded orthogonal path through them
 * (the caller is responsible for setting waypoints only when the curve hits an obstacle —
 * see `curveHitsObstacle`).
 *
 * Candidates are always empty — curved connections are not user-editable.
 */
export class CurvedPathBuilder implements IFConnectionBuilder {
    handle({ source, target, waypoints }: IFConnectionBuilderRequest): IFConnectionBuilderResponse {
        if (waypoints?.length) {
            return this.fromWaypoints(source, target, waypoints);
        }

        if (isWithinStraightLineThreshold(source, target)) {
            return straightLine(source, target);
        }

        const exitX = source.x + STUB;
        const entryX = target.x - STUB;
        return entryX <= exitX
            ? this.backward(source, target, exitX, entryX)
            : this.forward(source, target, exitX, entryX);
    }

    private fromWaypoints(source: IPoint, target: IPoint, waypoints: IPoint[]): IFConnectionBuilderResponse {
        const interior = normalizeOrthogonalWaypoints(source, waypoints, target);
        const points = interior.length ? [source, ...interior, target] : fallbackRoutePoints(source, target);
        const path = buildRoundedOrthogonalPath(points, MAX_ARC_RADIUS);
        return {
            path,
            points,
            secondPoint: points[1],
            penultimatePoint: points[points.length - 2],
            candidates: [],
        };
    }

    private forward(source: IPoint, target: IPoint, exitX: number, entryX: number): IFConnectionBuilderResponse {
        const gap = entryX - exitX;
        const offset = clamp(gap * OFFSET_RATIO, MIN_OFFSET, MAX_OFFSET);

        const exitPoint: IPoint = { x: exitX, y: source.y };
        const entryPoint: IPoint = { x: entryX, y: target.y };

        const path =
            `M ${source.x} ${source.y}` +
            ` L ${exitPoint.x} ${exitPoint.y}` +
            ` C ${exitX + offset} ${source.y}, ${entryX - offset} ${target.y}, ${entryPoint.x} ${entryPoint.y}` +
            ` L ${target.x + 0.0002} ${target.y + 0.0002}`;

        return {
            path,
            points: [source, exitPoint, entryPoint, target],
            secondPoint: exitPoint,
            penultimatePoint: entryPoint,
            candidates: [],
        };
    }

    /**
     * Backward routing: S-curve between nodes when vertical gap is large
     * enough, rounded-rectangle loop above when it isn't.
     */
    private backward(source: IPoint, target: IPoint, exitX: number, entryX: number): IFConnectionBuilderResponse {
        const verticalGap = source.y - target.y;

        if (Math.abs(verticalGap) < STUB) {
            return this.backwardLoop(source, target, exitX, entryX);
        }
        return this.backwardSCurve(source, target, exitX, entryX, verticalGap);
    }

    /**
     * S-curve for backward connections with sufficient vertical gap.
     * Works in both directions:
     *   sign = +1  (target above): exit circle above, entry circle below
     *   sign = −1  (target below): exit circle below, entry circle above
     *
     * Three segments (plus horizontal stubs):
     *   Exit arc → straight tangent line ("\" direction) → entry arc
     *
     *   sign=+1:                    sign=−1:
     *   target ──(entry)╲           source ──(exit)╲
     *                     ╲                          ╲
     *                (exit)──source            (entry)──target
     */
    private backwardSCurve(
        source: IPoint,
        target: IPoint,
        exitX: number,
        entryX: number,
        verticalGap: number
    ): IFConnectionBuilderResponse {
        const exitPoint: IPoint = { x: exitX, y: source.y };
        const entryPoint: IPoint = { x: entryX, y: target.y };

        const absGap = Math.abs(verticalGap);
        const sign = verticalGap >= 0 ? 1 : -1;

        const horizontalGap = exitX - entryX;
        const straightDistance = Math.sqrt(horizontalGap * horizontalGap + absGap * absGap);

        // R < absGap/4 guarantees the tangent line goes "\" direction.
        const maxRadiusForSlash = Math.floor(absGap / 4) - 1;
        if (maxRadiusForSlash < MIN_ARC_RADIUS || horizontalGap > 740) {
            return this.backwardLoop(source, target, exitX, entryX);
        }

        let radius = clamp(
            straightDistance * ARC_RADIUS_RATIO,
            MIN_ARC_RADIUS,
            Math.min(MAX_ARC_RADIUS, maxRadiusForSlash)
        );

        // Circle centers: exit toward target side, entry toward source side
        let cExitY = source.y - sign * radius;
        let cEntryY = target.y + sign * radius;

        const centerDx = entryX - exitX;
        let centerDy = cEntryY - cExitY;
        let centerDistance = Math.sqrt(centerDx * centerDx + centerDy * centerDy);

        // Shrink radius if internal tangent doesn't exist (circles overlap)
        if (centerDistance < 2 * radius) {
            radius = Math.max(Math.floor(centerDistance / 2) - 1, MIN_ARC_RADIUS);
            cExitY = source.y - sign * radius;
            cEntryY = target.y + sign * radius;
            centerDy = cEntryY - cExitY;
            centerDistance = Math.sqrt(centerDx * centerDx + centerDy * centerDy);
        }

        // Internal tangent — sign picks the correct tangent solution
        const theta = Math.atan2(centerDy, centerDx);
        const alpha = Math.acos(clamp((2 * radius) / centerDistance, -1, 1));
        const contactAngle = theta + sign * alpha;

        const cosContact = Math.cos(contactAngle);
        const sinContact = Math.sin(contactAngle);

        const tangentExitPoint: IPoint = {
            x: exitX + radius * cosContact,
            y: cExitY + radius * sinContact,
        };
        const tangentEntryPoint: IPoint = {
            x: entryX - radius * cosContact,
            y: cEntryY - radius * sinContact,
        };

        // Arc span — generalized for both directions
        const TAU = 2 * Math.PI;
        const arcSpan = (((Math.PI / 2 - sign * contactAngle) % TAU) + TAU) % TAU;
        const largeArc = arcSpan > Math.PI ? 1 : 0;

        // sign=+1: exit sweep=0 (CCW), entry sweep=1 (CW)
        // sign=−1: exit sweep=1 (CW), entry sweep=0 (CCW)
        const exitSweep = sign > 0 ? 0 : 1;
        const entrySweep = 1 - exitSweep;

        const path =
            `M ${source.x} ${source.y}` +
            ` L ${exitPoint.x} ${exitPoint.y}` +
            ` A ${radius} ${radius} 0 ${largeArc} ${exitSweep} ${tangentExitPoint.x} ${tangentExitPoint.y}` +
            ` L ${tangentEntryPoint.x} ${tangentEntryPoint.y}` +
            ` A ${radius} ${radius} 0 ${largeArc} ${entrySweep} ${entryPoint.x} ${entryPoint.y}` +
            ` L ${target.x + 0.0002} ${target.y + 0.0002}`;

        return {
            path,
            points: [source, exitPoint, tangentExitPoint, tangentEntryPoint, entryPoint, target],
            secondPoint: exitPoint,
            penultimatePoint: entryPoint,
            candidates: [],
        };
    }

    /**
     * Rounded-rectangle loop above both nodes.
     * Four quarter-circle arcs (all sweep=0 / CCW) at the corners,
     * connected by straight line segments.
     *
     *              ╭─── top horizontal ───╮
     *        arc2  │                      │  arc3
     *              │  right vertical      │  left vertical
     *        arc1  │                      │  arc4
     *   source ──exit                    entry── target
     */
    private backwardLoop(source: IPoint, target: IPoint, exitX: number, entryX: number): IFConnectionBuilderResponse {
        const exitPoint: IPoint = { x: exitX, y: source.y };
        const entryPoint: IPoint = { x: entryX, y: target.y };

        const horizontalGap = exitX - entryX;
        const verticalDiff = Math.abs(source.y - target.y);
        const loopSpan = Math.sqrt(horizontalGap * horizontalGap + verticalDiff * verticalDiff);

        const radius = clamp(loopSpan * LOOP_RADIUS_RATIO, MIN_ARC_RADIUS, LOOP_MAX_RADIUS);

        // Top of the loop: 2R above the higher node
        const topY = Math.min(source.y, target.y) - 2 * radius;

        // Four corner arc endpoints (each arc is 90°, sweep=0):
        // 1) bottom-right: exitPoint → right side
        const afterArc1: IPoint = { x: exitX + radius, y: source.y - radius };
        // 2) top-right: right side → top
        const beforeArc2: IPoint = { x: exitX + radius, y: topY + radius };
        const afterArc2: IPoint = { x: exitX, y: topY };
        // 3) top-left: top → left side
        const afterArc3: IPoint = { x: entryX - radius, y: topY + radius };
        // 4) bottom-left: left side → entryPoint
        const beforeArc4: IPoint = { x: entryX - radius, y: target.y - radius };

        const path =
            `M ${source.x} ${source.y}` +
            ` L ${exitPoint.x} ${exitPoint.y}` +
            ` A ${radius} ${radius} 0 0 0 ${afterArc1.x} ${afterArc1.y}` +
            ` L ${beforeArc2.x} ${beforeArc2.y}` +
            ` A ${radius} ${radius} 0 0 0 ${afterArc2.x} ${afterArc2.y}` +
            ` L ${entryX} ${topY}` +
            ` A ${radius} ${radius} 0 0 0 ${afterArc3.x} ${afterArc3.y}` +
            ` L ${beforeArc4.x} ${beforeArc4.y}` +
            ` A ${radius} ${radius} 0 0 0 ${entryPoint.x} ${entryPoint.y}` +
            ` L ${target.x + 0.0002} ${target.y + 0.0002}`;

        return {
            path,
            points: [source, exitPoint, afterArc2, { x: entryX, y: topY }, entryPoint, target],
            secondPoint: exitPoint,
            penultimatePoint: entryPoint,
            candidates: [],
        };
    }
}

// ── Curve sampling for obstacle detection ──────────────────────────────────────
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
    if (Math.abs(verticalGap) < STUB) {
        return backwardLoopCurveSamplePoints(source, target, exitX, entryX);
    }
    return backwardSCurveCurveSamplePoints(source, target, exitX, entryX, verticalGap);
}

function backwardSCurveCurveSamplePoints(
    source: IPoint,
    target: IPoint,
    exitX: number,
    entryX: number,
    verticalGap: number
): IPoint[] {
    const absGap = Math.abs(verticalGap);
    const sign = verticalGap >= 0 ? 1 : -1;
    const horizontalGap = exitX - entryX;
    const straightDistance = Math.sqrt(horizontalGap * horizontalGap + absGap * absGap);
    const maxRadiusForSlash = Math.floor(absGap / 4) - 1;

    if (maxRadiusForSlash < MIN_ARC_RADIUS) {
        return backwardLoopCurveSamplePoints(source, target, exitX, entryX);
    }

    let radius = clamp(
        straightDistance * ARC_RADIUS_RATIO,
        MIN_ARC_RADIUS,
        Math.min(MAX_ARC_RADIUS, maxRadiusForSlash)
    );
    let cExitY = source.y - sign * radius;
    let cEntryY = target.y + sign * radius;
    const centerDx = entryX - exitX;
    let centerDy = cEntryY - cExitY;
    let centerDistance = Math.sqrt(centerDx * centerDx + centerDy * centerDy);

    if (centerDistance < 2 * radius) {
        radius = Math.max(Math.floor(centerDistance / 2) - 1, MIN_ARC_RADIUS);
        cExitY = source.y - sign * radius;
        cEntryY = target.y + sign * radius;
        centerDy = cEntryY - cExitY;
        centerDistance = Math.sqrt(centerDx * centerDx + centerDy * centerDy);
        if (centerDistance < 2 * radius) {
            return backwardLoopCurveSamplePoints(source, target, exitX, entryX);
        }
    }

    const theta = Math.atan2(centerDy, centerDx);
    const alpha = Math.acos(clamp((2 * radius) / centerDistance, -1, 1));
    const contactAngle = theta + sign * alpha;

    const exitCenter: IPoint = { x: exitX, y: cExitY };
    const entryCenter: IPoint = { x: entryX, y: cEntryY };
    const tangentExitPoint: IPoint = {
        x: exitX + radius * Math.cos(contactAngle),
        y: cExitY + radius * Math.sin(contactAngle),
    };
    const tangentEntryPoint: IPoint = {
        x: entryX - radius * Math.cos(contactAngle),
        y: cEntryY - radius * Math.sin(contactAngle),
    };

    if (sign * (tangentExitPoint.y - tangentEntryPoint.y) <= 0) {
        return backwardLoopCurveSamplePoints(source, target, exitX, entryX);
    }

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
    const horizontalGap = exitX - entryX;
    const verticalDiff = Math.abs(source.y - target.y);
    const loopSpan = Math.sqrt(horizontalGap * horizontalGap + verticalDiff * verticalDiff);
    const radius = clamp(loopSpan * LOOP_RADIUS_RATIO, MIN_ARC_RADIUS, LOOP_MAX_RADIUS);
    const topY = Math.min(source.y, target.y) - 2 * radius;

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

function isWithinStraightLineThreshold(source: IPoint, target: IPoint): boolean {
    const X_DISTANCE = target.x - source.x;
    const Y_DISTANCE = target.y - source.y;
    return (
        -1 <= X_DISTANCE && X_DISTANCE <= STRAIGHT_LINE_THRESHOLD && Math.abs(Y_DISTANCE) <= STRAIGHT_LINE_THRESHOLD + 1
    );
}

function straightLine(source: IPoint, target: IPoint): IFConnectionBuilderResponse {
    const path = `M ${source.x} ${source.y} L ${target.x + 0.0002} ${target.y + 0.0002}`;
    return {
        path,
        points: [source, target],
        secondPoint: target,
        penultimatePoint: source,
        candidates: [],
    };
}

function clamp(value: number, minimum: number, maximum: number): number {
    return Math.max(minimum, Math.min(maximum, value));
}

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
