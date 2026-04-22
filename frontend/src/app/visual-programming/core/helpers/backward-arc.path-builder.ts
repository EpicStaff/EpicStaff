import { IPoint } from '@foblex/2d';
import { IFConnectionBuilder, IFConnectionBuilderRequest, IFConnectionBuilderResponse } from '@foblex/flow';

import { NodeModel } from '../models/node.model';
import { getCollisionBounds } from './node-placement.utils';

const EXIT_OFFSET = 40;
const ENTRY_OFFSET = 40;
const ROUTE_MARGIN = 60;

const H_CLEARANCE = 20;
const V_CLEARANCE = 15;
const V_REACTION_PAD = 12;
const MAX_TOTAL_LIFT = 260;

function getNodeRect(node: NodeModel) {
    const b = getCollisionBounds(node);
    return {
        nLeft: node.position.x + b.offsetX,
        nTop: node.position.y + b.offsetY,
        nRight: node.position.x + b.offsetX + b.width,
        nBottom: node.position.y + b.offsetY + b.height,
    };
}

function rangesOverlap(a1: number, a2: number, b1: number, b2: number): boolean {
    return Math.max(a1, b1) < Math.min(a2, b2);
}

function avoidVertical(
    x: number,
    routeY: number,
    portY: number,
    direction: 'right' | 'left',
    nodes: NodeModel[]
): number {
    const yTop = Math.min(routeY, portY);
    const yBottom = Math.max(routeY, portY);

    let adjusted = x;

    for (let pass = 0; pass < 8; pass++) {
        let moved = false;

        for (const node of nodes) {
            const { nLeft, nTop, nRight, nBottom } = getNodeRect(node);

            const xTooClose = adjusted >= nLeft - V_REACTION_PAD && adjusted <= nRight + V_REACTION_PAD;

            const yOverlaps = rangesOverlap(yTop, yBottom, nTop, nBottom);

            if (!xTooClose || !yOverlaps) continue;

            const candidate = direction === 'right' ? nRight + V_CLEARANCE : nLeft - V_CLEARANCE;

            if (candidate !== adjusted) {
                adjusted = candidate;
                moved = true;
            }
        }

        if (!moved) break;
    }

    return adjusted;
}

function avoidHorizontal(
    routeY: number,
    sx2: number,
    tx2: number,
    source: IPoint,
    target: IPoint,
    nodes: NodeModel[]
): number {
    const corridorLeft = Math.min(sx2, tx2);
    const corridorRight = Math.max(sx2, tx2);
    const cap = Math.min(source.y, target.y) - MAX_TOTAL_LIFT;

    let adjusted = routeY;

    for (let pass = 0; pass < 8; pass++) {
        let moved = false;

        for (const node of nodes) {
            const { nLeft, nTop, nRight, nBottom } = getNodeRect(node);

            const overlapsCorridor = nLeft < corridorRight && nRight > corridorLeft;

            if (!overlapsCorridor) continue;

            const crossesOrTouchesBand = nBottom >= adjusted - H_CLEARANCE && nTop <= adjusted + H_CLEARANCE;

            if (!crossesOrTouchesBand) continue;

            const candidate = nTop - H_CLEARANCE;
            if (candidate < adjusted) {
                adjusted = candidate;
                moved = true;
            }
        }

        if (!moved) break;
    }

    return Math.max(cap, adjusted);
}

export function computeBackwardArcPoints(
    source: IPoint,
    target: IPoint,
    waypoints: IPoint[] | undefined,
    nodes: NodeModel[]
): IPoint[] {
    let sx2 = source.x + EXIT_OFFSET;
    let tx2 = target.x - ENTRY_OFFSET;

    const baseRouteY = waypoints && waypoints.length > 0 ? waypoints[0].y : Math.min(source.y, target.y) - ROUTE_MARGIN;

    sx2 = avoidVertical(sx2, baseRouteY, source.y, 'right', nodes);
    tx2 = avoidVertical(tx2, baseRouteY, target.y, 'left', nodes);

    const routeY = avoidHorizontal(baseRouteY, sx2, tx2, source, target, nodes);

    sx2 = avoidVertical(sx2, routeY, source.y, 'right', nodes);
    tx2 = avoidVertical(tx2, routeY, target.y, 'left', nodes);

    return [
        { x: source.x, y: source.y },
        { x: sx2, y: source.y },
        { x: sx2, y: routeY },
        { x: tx2, y: routeY },
        { x: tx2, y: target.y },
        { x: target.x, y: target.y },
    ];
}

export class BackwardArcPathBuilder implements IFConnectionBuilder {
    constructor(private readonly getNodes: () => NodeModel[] = () => []) {}

    public handle(request: IFConnectionBuilderRequest): IFConnectionBuilderResponse {
        const { source, target, radius, waypoints } = request;
        const nodes = this.getNodes();
        const points = computeBackwardArcPoints(source, target, waypoints, nodes);

        return {
            path: this.buildPath(points, radius),
            penultimatePoint: points[4],
            secondPoint: points[1],
            points,
            candidates: waypoints?.length ? [] : [{ x: (points[1].x + points[4].x) / 2, y: points[2].y }],
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
