import { IPoint } from '@foblex/2d';
import { IFConnectionBuilder, IFConnectionBuilderRequest, IFConnectionBuilderResponse } from '@foblex/flow';

import { buildCatmullRomPath, computeBackwardControlPoints, computeForwardControlPoints } from './curved-route-shapes';

/**
 * Foblex connection builder `'curved'`: draws `[source, ...waypoints, target]`
 * as a smooth Catmull-Rom spline converted to cubic Bezier SVG path segments.
 *
 * When the router provides waypoints they are used as through-points for the
 * spline. Without waypoints (while a node is dragged or before the router runs)
 * a fallback shape is computed: forward connections get a simple S-curve, and
 * backward connections loop above both nodes.
 *
 * Candidates are always empty — curved connections are not user-editable.
 */
export class CurvedPathBuilder implements IFConnectionBuilder {
    handle(request: IFConnectionBuilderRequest): IFConnectionBuilderResponse {
        const { source, target, waypoints } = request;

        const BACKWARD_THRESHOLD = 20;
        let allPoints: IPoint[];

        if (waypoints?.length) {
            // Router has provided through-points — use them directly
            allPoints = [source, ...waypoints, target];
        } else {
            // Fallback: no router waypoints — compute basic control points
            const isBackward = target.x < source.x - BACKWARD_THRESHOLD;
            const controlPoints = isBackward
                ? computeBackwardControlPoints(source, target, null, null)
                : computeForwardControlPoints(source, target);
            allPoints = [source, ...controlPoints, target];
        }

        const path = buildCatmullRomPath(allPoints);

        // secondPoint and penultimatePoint control arrow marker rotation.
        // They must be close to source/target for correct orientation.
        const secondPoint = allPoints.length > 1 ? allPoints[1] : target;
        const penultimatePoint = allPoints.length > 1 ? allPoints[allPoints.length - 2] : source;

        return {
            path,
            points: allPoints,
            secondPoint,
            penultimatePoint,
            candidates: [],
        };
    }
}
