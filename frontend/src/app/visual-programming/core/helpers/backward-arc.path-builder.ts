import { IPoint } from '@foblex/2d';
import { IFConnectionBuilder, IFConnectionBuilderRequest, IFConnectionBuilderResponse } from '@foblex/flow';

import { BaseNodeModel } from '../models/node.model';

// ─── tuning constants ────────────────────────────────────────────────────────
const EXIT_OFFSET = 40; // Minimum horizontal stub on exit  (right of source)
const ENTRY_OFFSET = 40; // Minimum horizontal stub on entry (left  of target)
const ROUTE_MARGIN = 60; // Default clearance above the higher port — kept small
// so routes stay compact; avoidance logic adds more only
// when a node actually sits in the path.
const H_CLEARANCE = 20; // Gap above a blocking node for the horizontal segment
const V_CLEARANCE = 15; // Gap beside a blocking node for a vertical segment
const MAX_TOTAL_LIFT = 260; // Hard cap: routeY can never go more than this far
// above min(source.y, target.y), regardless of obstacles.
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Renders backward (right-to-left) connections as a clean U-shaped arc
 * that routes above both endpoints.
 *
 * Local obstacle avoidance:
 *  1. sx2 (vertical exit x) is pushed rightward  if a node is in the rise path.
 *  2. tx2 (vertical entry x) is pushed leftward   if a node is in the descent path.
 *  3. routeY (horizontal top Y) is pushed upward  if a node straddles that level
 *     inside the corridor — but only up to MAX_TOTAL_LIFT above the ports.
 *
 * The checks are local: only nodes that physically intersect each individual
 * segment are considered. Nodes elsewhere on the canvas are ignored.
 *
 * Touching the midpoint candidate switches the connection to normal segment
 * routing (fType changes from 'backward-arc' to 'segment').
 */
export class BackwardArcPathBuilder implements IFConnectionBuilder {
    constructor(private readonly getNodes: () => BaseNodeModel[] = () => []) {}

    public handle(request: IFConnectionBuilderRequest): IFConnectionBuilderResponse {
        const { source, target, radius, waypoints } = request;
        const nodes = this.getNodes();

        // Step 1 — initial coordinates (compact defaults)
        let sx2 = source.x + EXIT_OFFSET;
        let tx2 = target.x - ENTRY_OFFSET;

        let routeY: number;
        let candidates: IPoint[];

        if (waypoints && waypoints.length > 0) {
            // User has positioned the arc — honour their chosen Y directly.
            // Vertical stubs still auto-avoid nodes so they don't clip.
            const baseRouteY = waypoints[0].y;
            sx2 = this.avoidVertical(sx2, baseRouteY, source.y, 'right', nodes);
            tx2 = this.avoidVertical(tx2, baseRouteY, target.y, 'left', nodes);
            routeY = baseRouteY;
            candidates = [];
        } else {
            // No user override — auto-route above both endpoints.
            const baseRouteY = Math.min(source.y, target.y) - ROUTE_MARGIN;
            sx2 = this.avoidVertical(sx2, baseRouteY, source.y, 'right', nodes);
            tx2 = this.avoidVertical(tx2, baseRouteY, target.y, 'left', nodes);
            routeY = this.avoidHorizontal(baseRouteY, sx2, tx2, source, target, nodes);
            candidates = [{ x: (sx2 + tx2) / 2, y: routeY }];
        }

        const points: IPoint[] = [
            { x: source.x, y: source.y },
            { x: sx2, y: source.y },
            { x: sx2, y: routeY },
            { x: tx2, y: routeY },
            { x: tx2, y: target.y },
            { x: target.x, y: target.y },
        ];

        return {
            path: this.buildPath(points, radius),
            penultimatePoint: { x: tx2, y: target.y },
            secondPoint: { x: sx2, y: source.y },
            points,
            candidates,
        };
    }

    // ─── segment-local avoidance helpers ─────────────────────────────────────

    /**
     * Pushes a vertical-segment x-coordinate past any node whose bounding
     * box contains it within the segment's Y-range.
     *
     * direction 'right' — for the exit stub; expands away from the source node.
     * direction 'left'  — for the entry stub; expands away from the target node.
     *
     * Iterates up to 8 times to handle chains of adjacent nodes.
     */
    private avoidVertical(
        x: number,
        routeY: number,
        portY: number,
        direction: 'right' | 'left',
        nodes: BaseNodeModel[]
    ): number {
        const yTop = Math.min(routeY, portY);
        const yBottom = Math.max(routeY, portY);
        let adjusted = x;

        for (let pass = 0; pass < 8; pass++) {
            let moved = false;
            for (const node of nodes) {
                const nRight = node.position.x + node.size.width;
                const nBottom = node.position.y + node.size.height;

                if (
                    node.position.x < adjusted &&
                    nRight > adjusted && // x inside node
                    node.position.y < yBottom &&
                    nBottom > yTop // y-range overlaps
                ) {
                    adjusted = direction === 'right' ? nRight + V_CLEARANCE : node.position.x - V_CLEARANCE;
                    moved = true;
                }
            }
            if (!moved) break;
        }
        return adjusted;
    }

    /**
     * Pushes routeY upward (smaller Y) past any node that straddles it
     * within the horizontal corridor [min(sx2,tx2), max(sx2,tx2)].
     *
     * Iterates up to 8 times so that nodes stacked in multiple rows are all
     * cleared: pushing past a lower node can expose a higher node that was
     * previously entirely above the old routeY but now straddles the new one.
     *
     * Result is capped at MAX_TOTAL_LIFT above the higher port.
     */
    private avoidHorizontal(
        routeY: number,
        sx2: number,
        tx2: number,
        source: IPoint,
        target: IPoint,
        nodes: BaseNodeModel[]
    ): number {
        const corridorLeft = Math.min(sx2, tx2);
        const corridorRight = Math.max(sx2, tx2);
        const cap = Math.min(source.y, target.y) - MAX_TOTAL_LIFT;

        let adjusted = routeY;
        for (let pass = 0; pass < 8; pass++) {
            let moved = false;
            for (const node of nodes) {
                const nRight = node.position.x + node.size.width;
                const nBottom = node.position.y + node.size.height;

                // Skip: no horizontal overlap with corridor
                if (node.position.x >= corridorRight || nRight <= corridorLeft) continue;

                // Skip: node entirely above or entirely below the segment
                if (nBottom < adjusted || node.position.y > adjusted) continue;

                // Node straddles the planned segment — push just above it
                const candidate = node.position.y - H_CLEARANCE;
                if (candidate < adjusted) {
                    adjusted = candidate;
                    moved = true;
                }
            }
            if (!moved) break;
        }

        // Never go above the hard cap
        return Math.max(cap, adjusted);
    }

    // ─── path geometry ────────────────────────────────────────────────────────

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
