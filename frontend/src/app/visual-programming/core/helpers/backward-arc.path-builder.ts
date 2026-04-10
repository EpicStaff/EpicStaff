import { IPoint } from '@foblex/2d';
import { IFConnectionBuilder, IFConnectionBuilderRequest, IFConnectionBuilderResponse } from '@foblex/flow';

const EXIT_OFFSET = 30;
const ENTRY_OFFSET = 30;
const ROUTE_MARGIN = 150;

export class BackwardArcPathBuilder implements IFConnectionBuilder {
    public handle(request: IFConnectionBuilderRequest): IFConnectionBuilderResponse {
        const { source, target } = request;

        const sx2 = source.x + EXIT_OFFSET;
        const tx2 = target.x - ENTRY_OFFSET;
        const routeY = Math.min(source.y, target.y) - ROUTE_MARGIN;

        const points: IPoint[] = [
            { x: source.x, y: source.y },
            { x: sx2, y: source.y },
            { x: sx2, y: routeY },
            { x: tx2, y: routeY },
            { x: tx2, y: target.y },
            { x: target.x, y: target.y },
        ];

        return {
            path: this.buildPath(points, request.radius),
            connectionCenter: { x: (sx2 + tx2) / 2, y: routeY },
            penultimatePoint: { x: tx2, y: target.y },
            secondPoint: { x: sx2, y: source.y },
        };
    }

    private buildPath(points: IPoint[], radius: number): string {
        let path = '';
        for (let i = 0; i < points.length; i++) {
            const p = points[i];
            if (i === 0) {
                path += `M ${p.x} ${p.y}`;
            } else if (i === points.length - 1) {
                path += `L ${p.x + 0.0002} ${p.y + 0.0002}`;
            } else {
                path += this.getBend(points[i - 1], p, points[i + 1], radius);
            }
        }
        return path;
    }

    // Identical to FSegmentPathBuilder.getBend — produces a quadratic-bezier
    // rounded corner matching the system connection style.
    private getBend(a: IPoint, b: IPoint, c: IPoint, size: number): string {
        const bendSize = Math.min(this.distance(a, b) / 2, this.distance(b, c) / 2, size);
        const { x, y } = b;

        if ((a.x === x && x === c.x) || (a.y === y && y === c.y)) {
            return `L ${x} ${y}`;
        }

        if (a.y === y) {
            const xDir = a.x < c.x ? -1 : 1;
            const yDir = a.y < c.y ? 1 : -1;
            return `L ${x + bendSize * xDir},${y} Q ${x},${y} ${x},${y + bendSize * yDir}`;
        }

        const xDir = a.x < c.x ? 1 : -1;
        const yDir = a.y < c.y ? -1 : 1;
        return `L ${x},${y + bendSize * yDir} Q ${x},${y} ${x + bendSize * xDir},${y}`;
    }

    private distance(a: IPoint, b: IPoint): number {
        return Math.sqrt(Math.pow(b.x - a.x, 2) + Math.pow(b.y - a.y, 2));
    }
}
