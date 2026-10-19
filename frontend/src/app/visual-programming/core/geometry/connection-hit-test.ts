import { IPoint } from '@foblex/2d';

import { segmentIntersectsRect, SegmentRect } from './segment-math';

export type Rect = SegmentRect;

/** Whether any segment of the polyline intersects the rectangle. */
export function polylineIntersectsRect(pathPoints: IPoint[], rect: Rect): boolean {
    for (let i = 0; i < pathPoints.length - 1; i++) {
        if (segmentIntersectsRect(pathPoints[i], pathPoints[i + 1], rect)) {
            return true;
        }
    }
    return false;
}
