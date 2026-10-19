import { IPoint } from '@foblex/2d';
import { IFConnectionBuilder, IFConnectionBuilderRequest, IFConnectionBuilderResponse } from '@foblex/flow';

import {
    buildRoundedOrthogonalPath,
    fallbackRoutePoints,
    normalizeOrthogonalWaypoints,
    orthogonalStretches,
} from './orthogonal-route-shapes';
import { isWithinStraightLineThreshold, straightLine } from './path-builder-shared';

const STRAIGHT_LINE_THRESHOLD = 30;

/**
 * Foblex connection builder `'orthogonal'`: draws `[source, ...waypoints, target]`
 * through `normalizeOrthogonalWaypoints`. On the router's points that is exactly those points (made
 * orthogonal against the pixel or two Foblex's DOM port points can differ by); mid-drag, a dragged
 * candidate is drawn as the stretch it moves. Without waypoints (while a node is dragged or
 * animated) it draws the fallback shape.
 *
 * Candidates: one per stretch between consecutive normalized interior points, on the middle of its
 * middle segment. Using the normalized interior (instead of the raw waypoints) ensures candidates
 * sit on the rendered path — keepStubs and collapseShortBridges can shift the shape away from the
 * raw waypoints. Foblex inserts a dragged candidate at `candidates.indexOf(candidate)` inside the
 * current waypoints array; after release, `onWaypointsChanged` re-normalizes.
 */
export class OrthogonalPathBuilder implements IFConnectionBuilder {
    handle({ source, target, radius, waypoints }: IFConnectionBuilderRequest): IFConnectionBuilderResponse {
        if (isWithinStraightLineThreshold(source, target, STRAIGHT_LINE_THRESHOLD)) {
            return straightLine(source, target);
        }

        const interior = waypoints?.length ? normalizeOrthogonalWaypoints(source, waypoints, target) : [];
        const points = interior.length ? [source, ...interior, target] : fallbackRoutePoints(source, target);
        const stretches = interior.length ? orthogonalStretches(source, interior, target) : segmentPairs(points);
        return {
            path: buildRoundedOrthogonalPath(points, radius),
            points,
            secondPoint: points[1],
            penultimatePoint: points[points.length - 2],
            candidates: stretches.map(middleOfMiddleSegment),
        };
    }
}

function segmentPairs(points: IPoint[]): IPoint[][] {
    const pairs: IPoint[][] = [];
    for (let i = 0; i < points.length - 1; i++) {
        pairs.push([points[i], points[i + 1]]);
    }
    return pairs;
}

function middleOfMiddleSegment(stretch: IPoint[]): IPoint {
    const segment = Math.floor((stretch.length - 2) / 2);
    const start = stretch[segment];
    const end = stretch[segment + 1];
    return { x: (start.x + end.x) / 2, y: (start.y + end.y) / 2 };
}
