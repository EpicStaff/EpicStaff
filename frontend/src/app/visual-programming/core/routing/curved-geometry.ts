import { IPoint } from '@foblex/2d';

import { clamp } from './path-builder-shared';

// ── Constants shared by the builder and obstacle detection ──────────────────

export const CURVED_STUB = 20;
export const CURVED_STRAIGHT_LINE_THRESHOLD = 60;
export const MAX_ARC_RADIUS = 80;
export const MIN_OFFSET = 20;
export const MAX_OFFSET = 300;
export const OFFSET_RATIO = 0.4;

const MIN_ARC_RADIUS = 15;
const ARC_RADIUS_RATIO = 0.12;
const LOOP_RADIUS_RATIO = 0.1;
const LOOP_MAX_RADIUS = 40;

// ── Shared geometry computation ─────────────────────────────────────────────
//
// These structs and functions are shared between the SVG-path builders (which
// produce `d` attribute strings) and the curve-sampling functions (which produce
// polyline approximations for obstacle detection).

export interface SCurveGeometry {
    radius: number;
    exitCircleY: number;
    entryCircleY: number;
    tangentExitPoint: IPoint;
    tangentEntryPoint: IPoint;
    contactAngle: number;
    centerDistance: number;
}

/**
 * Computes the shared S-curve geometry: arc radius, circle centers, and tangent
 * points. Returns `null` when the geometry degenerates and the caller should
 * fall back to a loop.
 */
export function computeBackwardSCurveGeometry(
    source: IPoint,
    target: IPoint,
    exitX: number,
    entryX: number,
    verticalGap: number
): SCurveGeometry | null {
    const absGap = Math.abs(verticalGap);
    const sign = verticalGap >= 0 ? 1 : -1;
    const horizontalGap = exitX - entryX;
    const straightDistance = Math.sqrt(horizontalGap * horizontalGap + absGap * absGap);

    // R < absGap/4 guarantees the tangent line goes "\" direction.
    const maxRadiusForSlash = Math.floor(absGap / 4) - 1;
    if (maxRadiusForSlash < MIN_ARC_RADIUS) return null;

    let radius = clamp(
        straightDistance * ARC_RADIUS_RATIO,
        MIN_ARC_RADIUS,
        Math.min(MAX_ARC_RADIUS, maxRadiusForSlash)
    );

    // Circle centers: exit toward target side, entry toward source side
    let exitCircleY = source.y - sign * radius;
    let entryCircleY = target.y + sign * radius;

    const centerDx = entryX - exitX;
    let centerDy = entryCircleY - exitCircleY;
    let centerDistance = Math.sqrt(centerDx * centerDx + centerDy * centerDy);

    // Shrink radius if internal tangent doesn't exist (circles overlap)
    if (centerDistance < 2 * radius) {
        radius = Math.max(Math.floor(centerDistance / 2) - 1, MIN_ARC_RADIUS);
        exitCircleY = source.y - sign * radius;
        entryCircleY = target.y + sign * radius;
        centerDy = entryCircleY - exitCircleY;
        centerDistance = Math.sqrt(centerDx * centerDx + centerDy * centerDy);
        if (centerDistance < 2 * radius) return null;
    }

    // Internal tangent — sign picks the correct tangent solution
    const theta = Math.atan2(centerDy, centerDx);
    const alpha = Math.acos(clamp((2 * radius) / centerDistance, -1, 1));
    const contactAngle = theta + sign * alpha;

    const cosContact = Math.cos(contactAngle);
    const sinContact = Math.sin(contactAngle);

    const tangentExitPoint: IPoint = {
        x: exitX + radius * cosContact,
        y: exitCircleY + radius * sinContact,
    };
    const tangentEntryPoint: IPoint = {
        x: entryX - radius * cosContact,
        y: entryCircleY - radius * sinContact,
    };

    return { radius, exitCircleY, entryCircleY, tangentExitPoint, tangentEntryPoint, contactAngle, centerDistance };
}

export interface LoopGeometry {
    radius: number;
    topY: number;
}

/** Computes the shared backward-loop geometry: arc radius and top-of-loop Y coordinate. */
export function computeBackwardLoopGeometry(
    source: IPoint,
    target: IPoint,
    exitX: number,
    entryX: number
): LoopGeometry {
    const horizontalGap = exitX - entryX;
    const verticalDiff = Math.abs(source.y - target.y);
    const loopSpan = Math.sqrt(horizontalGap * horizontalGap + verticalDiff * verticalDiff);
    const radius = clamp(loopSpan * LOOP_RADIUS_RATIO, MIN_ARC_RADIUS, LOOP_MAX_RADIUS);
    const topY = Math.min(source.y, target.y) - 2 * radius;
    return { radius, topY };
}
