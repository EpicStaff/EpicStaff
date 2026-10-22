import { IPoint } from '@foblex/2d';
import { IFConnectionBuilder, IFConnectionBuilderRequest, IFConnectionBuilderResponse } from '@foblex/flow';

import {
    computeBackwardLoopGeometry,
    computeBackwardSCurveGeometry,
    CURVED_STRAIGHT_LINE_THRESHOLD,
    CURVED_STUB,
    MAX_ARC_RADIUS,
    MAX_OFFSET,
    MIN_OFFSET,
    OFFSET_RATIO,
} from './curved-geometry';
import {
    buildRoundedOrthogonalPath,
    fallbackRoutePoints,
    normalizeOrthogonalWaypoints,
} from './orthogonal-route-shapes';
import { clamp, isWithinStraightLineThreshold, straightLine, SVG_ENDPOINT_NUDGE } from './path-builder-shared';

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

        if (isWithinStraightLineThreshold(source, target, CURVED_STRAIGHT_LINE_THRESHOLD)) {
            return straightLine(source, target);
        }

        const exitX = source.x + CURVED_STUB;
        const entryX = target.x - CURVED_STUB;
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
            ` L ${target.x + SVG_ENDPOINT_NUDGE} ${target.y + SVG_ENDPOINT_NUDGE}`;

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

        if (Math.abs(verticalGap) < CURVED_STUB) {
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
        const geometry = computeBackwardSCurveGeometry(source, target, exitX, entryX, verticalGap);
        if (!geometry) {
            return this.backwardLoop(source, target, exitX, entryX);
        }

        const { radius, tangentExitPoint, tangentEntryPoint, contactAngle } = geometry;
        const sign = verticalGap >= 0 ? 1 : -1;
        const exitPoint: IPoint = { x: exitX, y: source.y };
        const entryPoint: IPoint = { x: entryX, y: target.y };

        // Arc span — generalized for both directions
        const TAU = 2 * Math.PI;
        const arcSpan = (((Math.PI / 2 - sign * contactAngle) % TAU) + TAU) % TAU;
        const largeArc = arcSpan > Math.PI ? 1 : 0;

        // sign=+1: exit sweep=0 (CCW), entry sweep=1 (CW)
        // sign=-1: exit sweep=1 (CW), entry sweep=0 (CCW)
        const exitSweep = sign > 0 ? 0 : 1;
        const entrySweep = 1 - exitSweep;

        const path =
            `M ${source.x} ${source.y}` +
            ` L ${exitPoint.x} ${exitPoint.y}` +
            ` A ${radius} ${radius} 0 ${largeArc} ${exitSweep} ${tangentExitPoint.x} ${tangentExitPoint.y}` +
            ` L ${tangentEntryPoint.x} ${tangentEntryPoint.y}` +
            ` A ${radius} ${radius} 0 ${largeArc} ${entrySweep} ${entryPoint.x} ${entryPoint.y}` +
            ` L ${target.x + SVG_ENDPOINT_NUDGE} ${target.y + SVG_ENDPOINT_NUDGE}`;

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

        const { radius, topY } = computeBackwardLoopGeometry(source, target, exitX, entryX);

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
            ` L ${target.x + SVG_ENDPOINT_NUDGE} ${target.y + SVG_ENDPOINT_NUDGE}`;

        return {
            path,
            points: [source, exitPoint, afterArc2, { x: entryX, y: topY }, entryPoint, target],
            secondPoint: exitPoint,
            penultimatePoint: entryPoint,
            candidates: [],
        };
    }
}
