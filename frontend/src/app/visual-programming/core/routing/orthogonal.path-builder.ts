import { IPoint } from '@foblex/2d';
import { IFConnectionBuilder, IFConnectionBuilderRequest, IFConnectionBuilderResponse } from '@foblex/flow';

import {
    buildRoundedOrthogonalPath,
    fallbackRoutePoints,
    normalizeOrthogonalWaypoints,
    orthogonalStretches,
} from './orthogonal-route-shapes';

/**
 * Foblex connection builder `'orthogonal'`: draws `[source, ...waypoints, target]`
 * through `normalizeOrthogonalWaypoints`. On the router's points that is exactly those points (made
 * orthogonal against the pixel or two Foblex's DOM port points can differ by); mid-drag, a dragged
 * candidate is drawn as the stretch it moves. Without waypoints (while a node is dragged or
 * animated) it draws the fallback shape.
 *
 * Candidates: one per stretch between consecutive raw anchors, on the middle of its middle segment.
 * Foblex inserts a dragged candidate at raw waypoint index `candidates.indexOf(candidate)`, so
 * candidate i has to lie between raw waypoints i-1 and i.
 */
export class OrthogonalPathBuilder implements IFConnectionBuilder {
    handle({ source, target, radius, waypoints }: IFConnectionBuilderRequest): IFConnectionBuilderResponse {
        const interior = waypoints?.length ? normalizeOrthogonalWaypoints(source, waypoints, target) : [];
        const points = interior.length ? [source, ...interior, target] : fallbackRoutePoints(source, target);
        const stretches = waypoints?.length ? orthogonalStretches(source, waypoints, target) : [points];
        return {
            path: buildRoundedOrthogonalPath(points, radius),
            points,
            secondPoint: points[1],
            penultimatePoint: points[points.length - 2],
            candidates: stretches.map(middleOfMiddleSegment),
        };
    }
}

function middleOfMiddleSegment(stretch: IPoint[]): IPoint {
    const segment = Math.floor((stretch.length - 2) / 2);
    const start = stretch[segment];
    const end = stretch[segment + 1];
    return { x: (start.x + end.x) / 2, y: (start.y + end.y) / 2 };
}
