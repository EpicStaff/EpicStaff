import { IPoint } from '@foblex/2d';

export interface Rect {
    x: number;
    y: number;
    width: number;
    height: number;
}

/** Whether two line segments (a1→a2) and (b1→b2) intersect. */
function segmentsIntersect(a1: IPoint, a2: IPoint, b1: IPoint, b2: IPoint): boolean {
    const d1x = a2.x - a1.x;
    const d1y = a2.y - a1.y;
    const d2x = b2.x - b1.x;
    const d2y = b2.y - b1.y;

    const cross = d1x * d2y - d1y * d2x;
    const dx = b1.x - a1.x;
    const dy = b1.y - a1.y;

    if (Math.abs(cross) < 1e-10) {
        // Parallel — treat as non-intersecting for hit-test purposes
        return false;
    }

    const t = (dx * d2y - dy * d2x) / cross;
    const u = (dx * d1y - dy * d1x) / cross;

    return t >= 0 && t <= 1 && u >= 0 && u <= 1;
}

function pointInsideRect(point: IPoint, rect: Rect): boolean {
    return point.x >= rect.x && point.x <= rect.x + rect.width && point.y >= rect.y && point.y <= rect.y + rect.height;
}

/** Whether a line segment intersects or is contained within a rectangle. */
function segmentIntersectsRect(a: IPoint, b: IPoint, rect: Rect): boolean {
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

/** Whether any segment of the polyline intersects the rectangle. */
export function polylineIntersectsRect(pathPoints: IPoint[], rect: Rect): boolean {
    for (let i = 0; i < pathPoints.length - 1; i++) {
        if (segmentIntersectsRect(pathPoints[i], pathPoints[i + 1], rect)) {
            return true;
        }
    }
    return false;
}
