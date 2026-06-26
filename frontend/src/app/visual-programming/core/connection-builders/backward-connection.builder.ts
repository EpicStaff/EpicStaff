import {
    IFConnectionBuilder,
    IFConnectionBuilderRequest,
    IFConnectionBuilderResponse,
} from '@foblex/flow';
import { PointExtensions } from '@foblex/2d';

export class BackwardConnectionBuilder implements IFConnectionBuilder {
    public handle(request: IFConnectionBuilderRequest): IFConnectionBuilderResponse {
        const { source, target, offset } = request;

        // Horizontal step-out distance from ports
        const stepOut = 30;

        // Calculate clearance above nodes (use offset parameter)
        const clearance = offset || 80;

        // Determine the Y position for the horizontal segment
        // It should be above both source and target ports
        const horizontalY = Math.min(source.y, target.y) - clearance;

        // Create waypoints for RIGHT → UP → LEFT → DOWN → LEFT path
        const point1 = PointExtensions.initialize(source.x, source.y); // Start at source port
        const point2 = PointExtensions.initialize(source.x + stepOut, source.y); // Step OUT right
        const point3 = PointExtensions.initialize(source.x + stepOut, horizontalY); // Go UP
        const point4 = PointExtensions.initialize(target.x - stepOut, horizontalY); // Go LEFT
        const point5 = PointExtensions.initialize(target.x - stepOut, target.y); // Go DOWN
        const point6 = PointExtensions.initialize(target.x, target.y); // Step IN to target

        // Create SVG path
        const path = `M ${point1.x} ${point1.y} L ${point2.x} ${point2.y} L ${point3.x} ${point3.y} L ${point4.x} ${point4.y} L ${point5.x} ${point5.y} L ${point6.x} ${point6.y}`;

        return {
            path,
            penultimatePoint: point5,
            secondPoint: point2,
            points: [],
            candidates: [],
        };
    }
}
