import { IPoint } from '@foblex/2d';
import { IFConnectionBuilder, IFConnectionBuilderRequest, IFConnectionBuilderResponse } from '@foblex/flow';

const STUB = 20;
const MIN_OFFSET = 20;
const MAX_OFFSET = 300;
const OFFSET_RATIO = 0.4;
const MIN_ARC_RADIUS = 15;
const MAX_ARC_RADIUS = 80;
const ARC_RADIUS_RATIO = 0.12;
const LOOP_RADIUS_RATIO = 0.1;
const LOOP_MAX_RADIUS = 40;

/**
 * Foblex connection builder `'adaptive-curve'`: draws smooth cubic Bézier
 * curves with horizontal stubs at both ends.
 *
 * Forward connections (target right of source): stub → C curve → stub.
 * Backward with vertical gap (target upper-left): stub → arc → line → arc → stub (S-curve).
 * Backward without vertical gap: stub → arc → line → arc → stub (loop above).
 *
 * Candidates are always empty — curved connections are not user-editable.
 */
export class CurvedPathBuilder implements IFConnectionBuilder {
    handle({ source, target }: IFConnectionBuilderRequest): IFConnectionBuilderResponse {
        const exitX = source.x + STUB;
        const entryX = target.x - STUB;

        if (entryX <= exitX) {
            return this.backward(source, target, exitX, entryX);
        }

        return this.forward(source, target, exitX, entryX);
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
            ` L ${target.x} ${target.y}`;

        return {
            path,
            points: [source, exitPoint, entryPoint, target],
            secondPoint: exitPoint,
            penultimatePoint: entryPoint,
            candidates: [],
        };
    }

    /**
     * Backward S-curve using two circular arc segments connected by a straight
     * tangent line. The arcs use sin/cos for geometry and SVG `A` commands.
     *
     * When the vertical gap is too small for a clean S-curve, falls back to
     * a Bézier loop above both nodes.
     */
    private backward(source: IPoint, target: IPoint, exitX: number, entryX: number): IFConnectionBuilderResponse {
        const verticalGap = source.y - target.y;

        if (verticalGap < STUB) {
            return this.backwardLoop(source, target, exitX, entryX);
        }

        return this.backwardSCurve(source, target, exitX, entryX, verticalGap);
    }

    /**
     * S-curve for backward connections where target is above source.
     *
     * Three segments (plus horizontal stubs):
     *   (3) Exit arc — from exitPoint, curves upward (center above, sweep CCW)
     *   (2) Straight tangent line — connects the two arcs with G1 continuity
     *   (1) Entry arc — curves into entryPoint (center below, sweep CW)
     *
     * Arc radii and sector angles are derived from dx/dy via trigonometry.
     * The internal tangent between the two circles determines the connecting line.
     *
     *   target ──stub── (1) ╲
     *                         ╲  (2)
     *                           ╲
     *                       (3) ──stub── source
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

        const horizontalGap = exitX - entryX;
        const straightDistance = Math.sqrt(horizontalGap * horizontalGap + verticalGap * verticalGap);

        // R < verticalGap/4 guarantees the tangent line goes "\" direction.
        // When even MIN_ARC_RADIUS exceeds this cap, fall back to loop.
        const maxRadiusForSlash = Math.floor(verticalGap / 4) - 1;
        if (maxRadiusForSlash < MIN_ARC_RADIUS) {
            return this.backwardLoop(source, target, exitX, entryX);
        }

        let radius = clamp(
            straightDistance * ARC_RADIUS_RATIO,
            MIN_ARC_RADIUS,
            Math.min(MAX_ARC_RADIUS, maxRadiusForSlash)
        );

        // Circle centers: exit above exitPoint, entry below entryPoint
        let cExitY = source.y - radius;
        let cEntryY = target.y + radius;

        const centerDx = entryX - exitX;
        let centerDy = cEntryY - cExitY;
        let centerDistance = Math.sqrt(centerDx * centerDx + centerDy * centerDy);

        // Shrink radius if internal tangent doesn't exist (circles overlap)
        if (centerDistance < 2 * radius) {
            radius = Math.max(Math.floor(centerDistance / 2) - 1, MIN_ARC_RADIUS);
            cExitY = source.y - radius;
            cEntryY = target.y + radius;
            centerDy = cEntryY - cExitY;
            centerDistance = Math.sqrt(centerDx * centerDx + centerDy * centerDy);

            if (centerDistance < 2 * radius) {
                return this.backwardLoop(source, target, exitX, entryX);
            }
        }

        // Internal tangent between the two circles
        const theta = Math.atan2(centerDy, centerDx);
        const alpha = Math.acos(clamp((2 * radius) / centerDistance, -1, 1));
        const contactAngle = theta + alpha;

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

        // Tangent line must go "\" (upper-left → lower-right on screen).
        // If it goes "/" or is flat, fall back to the loop above.
        if (tangentEntryPoint.y >= tangentExitPoint.y) {
            return this.backwardLoop(source, target, exitX, entryX);
        }

        // Arc span (same for both arcs): sweep=0 goes DECREASING from π/2
        const arcSpan = (((Math.PI / 2 - contactAngle) % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
        const largeArc = arcSpan > Math.PI ? 1 : 0;

        // Exit arc: sweep=0 (CCW on screen → rightward tangent at exit)
        // Entry arc: sweep=1 (CW on screen → rightward tangent at entry)
        const path =
            `M ${source.x} ${source.y}` +
            ` L ${exitPoint.x} ${exitPoint.y}` +
            ` A ${radius} ${radius} 0 ${largeArc} 0 ${tangentExitPoint.x} ${tangentExitPoint.y}` +
            ` L ${tangentEntryPoint.x} ${tangentEntryPoint.y}` +
            ` A ${radius} ${radius} 0 ${largeArc} 1 ${entryPoint.x} ${entryPoint.y}` +
            ` L ${target.x} ${target.y}`;

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
            ` L ${target.x} ${target.y}`;

        return {
            path,
            points: [source, exitPoint, afterArc2, { x: entryX, y: topY }, entryPoint, target],
            secondPoint: exitPoint,
            penultimatePoint: entryPoint,
            candidates: [],
        };
    }
}

function clamp(value: number, minimum: number, maximum: number): number {
    return Math.max(minimum, Math.min(maximum, value));
}
