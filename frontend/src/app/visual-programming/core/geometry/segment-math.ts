import { IPoint } from '@foblex/2d';

/**
 * Shared segment-intersection primitives.
 *
 * Uses the orientation-based algorithm, which correctly handles collinear
 * and touching segments (unlike a pure cross-product test).
 */

/** Returns 0 for collinear, 1 for clockwise, 2 for counter-clockwise. */
export function orientation(a: IPoint, b: IPoint, c: IPoint): number {
    const value = (b.y - a.y) * (c.x - b.x) - (b.x - a.x) * (c.y - b.y);

    if (Math.abs(value) < 0.0001) return 0;

    return value > 0 ? 1 : 2;
}

/** Whether point `b` lies on segment `a--c`, given that `a`, `b`, `c` are collinear. */
export function onSegment(a: IPoint, b: IPoint, c: IPoint): boolean {
    return (
        b.x <= Math.max(a.x, c.x) + 0.0001 &&
        b.x >= Math.min(a.x, c.x) - 0.0001 &&
        b.y <= Math.max(a.y, c.y) + 0.0001 &&
        b.y >= Math.min(a.y, c.y) - 0.0001
    );
}

/** Whether two line segments (p1--q1) and (p2--q2) intersect, including collinear overlaps. */
export function segmentsIntersect(p1: IPoint, q1: IPoint, p2: IPoint, q2: IPoint): boolean {
    const o1 = orientation(p1, q1, p2);
    const o2 = orientation(p1, q1, q2);
    const o3 = orientation(p2, q2, p1);
    const o4 = orientation(p2, q2, q1);

    if (o1 !== o2 && o3 !== o4) return true;

    if (o1 === 0 && onSegment(p1, p2, q1)) return true;
    if (o2 === 0 && onSegment(p1, q2, q1)) return true;
    if (o3 === 0 && onSegment(p2, p1, q2)) return true;
    if (o4 === 0 && onSegment(p2, q1, q2)) return true;

    return false;
}

export interface SegmentRect {
    x: number;
    y: number;
    width: number;
    height: number;
}

/** Whether a point is inside or on the boundary of an axis-aligned rectangle. */
export function pointInsideRect(point: IPoint, rect: SegmentRect): boolean {
    return point.x >= rect.x && point.x <= rect.x + rect.width && point.y >= rect.y && point.y <= rect.y + rect.height;
}

/** Whether a line segment intersects or is contained within an axis-aligned rectangle. */
export function segmentIntersectsRect(a: IPoint, b: IPoint, rect: SegmentRect): boolean {
    if (pointInsideRect(a, rect) || pointInsideRect(b, rect)) {
        return true;
    }

    const topLeft: IPoint = { x: rect.x, y: rect.y };
    const topRight: IPoint = { x: rect.x + rect.width, y: rect.y };
    const bottomRight: IPoint = { x: rect.x + rect.width, y: rect.y + rect.height };
    const bottomLeft: IPoint = { x: rect.x, y: rect.y + rect.height };

    return (
        segmentsIntersect(a, b, topLeft, topRight) ||
        segmentsIntersect(a, b, topRight, bottomRight) ||
        segmentsIntersect(a, b, bottomRight, bottomLeft) ||
        segmentsIntersect(a, b, bottomLeft, topLeft)
    );
}
