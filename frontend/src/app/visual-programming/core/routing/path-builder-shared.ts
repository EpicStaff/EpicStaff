import { IPoint } from '@foblex/2d';
import { IFConnectionBuilderResponse } from '@foblex/flow';

// Tiny offset added to the SVG endpoint so the path has non-zero length even when
// source and target coincide — prevents the browser from collapsing the path to nothing.
export const SVG_ENDPOINT_NUDGE = 0.0002;

export function clamp(value: number, minimum: number, maximum: number): number {
    return Math.max(minimum, Math.min(maximum, value));
}

export function isWithinStraightLineThreshold(source: IPoint, target: IPoint, threshold: number): boolean {
    const xDistance = target.x - source.x;
    const yDistance = target.y - source.y;
    return -1 <= xDistance && xDistance <= threshold && Math.abs(yDistance) <= threshold + 1;
}

export function straightLine(source: IPoint, target: IPoint): IFConnectionBuilderResponse {
    const path = `M ${source.x} ${source.y} L ${target.x + SVG_ENDPOINT_NUDGE} ${target.y + SVG_ENDPOINT_NUDGE}`;
    return {
        path,
        points: [source, target],
        secondPoint: target,
        penultimatePoint: source,
        candidates: [],
    };
}
