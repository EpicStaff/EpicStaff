import { IPoint } from '@foblex/2d';

import { getPortPosition } from '../geometry/port-position';
import { flow8, FlowFixture, stackedPair } from '../layout/testing/fixtures';
import {
    buildRoundedOrthogonalPath,
    fallbackRoutePoints,
    normalizeOrthogonalWaypoints,
    orthogonalize,
} from './orthogonal-route-shapes';
import { resolveWireEnds, routeAll } from './route-all';

describe('buildRoundedOrthogonalPath', () => {
    it('gives the backward-arc builder’s string for its 6-point arc', () => {
        const arc = [
            { x: 100, y: 200 },
            { x: 140, y: 200 },
            { x: 140, y: 140 },
            { x: 10, y: 140 },
            { x: 10, y: 260 },
            { x: 50, y: 260 },
        ];

        // The exact path string, locked so any change to the corner rounding shows up here.
        expect(buildRoundedOrthogonalPath(arc, 8)).toBe(
            'M 100 200L 132,200 Q 140,200 140,192L 140,148 Q 140,140 132,140L 18,140 Q 10,140 10,148L 10,252 Q 10,260 18,260L 50.0002 260.0002'
        );
    });
});

describe('orthogonalize', () => {
    it('snaps the first and last waypoint onto the port rows when they are within 3 px', () => {
        const points = orthogonalize(
            { x: 0, y: 0 },
            [
                { x: 40, y: 2 },
                { x: 40, y: 100 },
            ],
            { x: 80, y: 101 }
        );

        expect(points).toEqual([
            { x: 0, y: 0 },
            { x: 40, y: 0 },
            { x: 40, y: 101 },
            { x: 80, y: 101 },
        ]);
    });

    it('leaves a waypoint more than 3 px off the port row alone and adds an elbow instead', () => {
        const points = orthogonalize({ x: 0, y: 0 }, [{ x: 40, y: 10 }], { x: 80, y: 10 });

        expect(points).toEqual([
            { x: 0, y: 0 },
            { x: 40, y: 0 },
            { x: 40, y: 10 },
            { x: 80, y: 10 },
        ]);
    });

    it('turns each diagonal pair into an elbow that continues the previous leg’s axis', () => {
        const points = orthogonalize(
            { x: 0, y: 0 },
            [
                { x: 50, y: 60 },
                { x: 120, y: 100 },
            ],
            { x: 200, y: 100 }
        );

        // Out of the source horizontally, so the first elbow goes horizontal first; the leg into
        // (50, 60) is vertical, so the next elbow goes vertical first.
        expect(points).toEqual([
            { x: 0, y: 0 },
            { x: 50, y: 0 },
            { x: 50, y: 60 },
            { x: 50, y: 100 },
            { x: 120, y: 100 },
            { x: 200, y: 100 },
        ]);
    });
});

describe('fallbackRoutePoints', () => {
    it('draws a forward wire as 4 points with the riser at mid x', () => {
        expect(fallbackRoutePoints({ x: 0, y: 0 }, { x: 200, y: 100 })).toEqual([
            { x: 0, y: 0 },
            { x: 100, y: 0 },
            { x: 100, y: 100 },
            { x: 200, y: 100 },
        ]);
    });

    it('returns a stacked wire (target left of and below the source) through the midpoint y, never above the source', () => {
        // Py#14 (0,0) → Py#15 (0,120), 330×60: ports at (335, 30) and (-5, 150).
        const points = fallbackRoutePoints({ x: 335, y: 30 }, { x: -5, y: 150 });

        expect(points).toEqual([
            { x: 335, y: 30 },
            { x: 355, y: 30 },
            { x: 355, y: 90 },
            { x: -25, y: 90 },
            { x: -25, y: 150 },
            { x: -5, y: 150 },
        ]);
        expect(points.every((point) => point.y >= 30)).toBe(true);
    });

    it('drops a backward wire between ports on nearly the same row below both of them', () => {
        const points = fallbackRoutePoints({ x: 335, y: 30 }, { x: -5, y: 40 });

        const leg = points.find((point, index) => index > 0 && point.y === points[index - 1].y && point.x < 0)!;
        expect(leg.y).toBeGreaterThan(40);
        expect(points[1]).toEqual({ x: 355, y: 30 });
        expect(points[points.length - 2]).toEqual({ x: -25, y: 40 });
    });
});

describe('normalizeOrthogonalWaypoints', () => {
    // A forward wire as the router draws it: out 20+, a riser at x = 100, in.
    const source = { x: 0, y: 0 };
    const target = { x: 200, y: 100 };
    const routed = [
        { x: 100, y: 0 },
        { x: 100, y: 100 },
    ];

    it('moves the riser to where its dragged middle point went', () => {
        // Foblex inserted the riser's candidate between the two bends, then the drag moved it.
        const dragged = [routed[0], { x: 140, y: 50 }, routed[1]];

        expect(normalizeOrthogonalWaypoints(source, dragged, target)).toEqual([
            { x: 140, y: 0 },
            { x: 140, y: 100 },
        ]);
    });

    it('keeps the source stub and jogs to the new row when the first stub is dragged', () => {
        const dragged = [{ x: 50, y: -40 }, ...routed];

        expect(normalizeOrthogonalWaypoints(source, dragged, target)).toEqual([
            { x: 20, y: 0 },
            { x: 20, y: -40 },
            { x: 100, y: -40 },
            { x: 100, y: 100 },
        ]);
    });

    it('keeps the target stub when the last stub is dragged', () => {
        const dragged = [...routed, { x: 150, y: 140 }];

        expect(normalizeOrthogonalWaypoints(source, dragged, target)).toEqual([
            { x: 100, y: 0 },
            { x: 100, y: 140 },
            { x: 180, y: 140 },
            { x: 180, y: 100 },
        ]);
    });

    it('bumps a straight wire out between its two stubs', () => {
        expect(normalizeOrthogonalWaypoints({ x: 0, y: 0 }, [{ x: 100, y: -50 }], { x: 200, y: 0 })).toEqual([
            { x: 20, y: 0 },
            { x: 20, y: -50 },
            { x: 180, y: -50 },
            { x: 180, y: 0 },
        ]);
    });

    it('turns the fallback wire’s dragged candidate into a riser at its x', () => {
        // No waypoints: the builder drew the fallback, whose one candidate sits on the riser.
        expect(normalizeOrthogonalWaypoints(source, [{ x: 140, y: 50 }], target)).toEqual([
            { x: 140, y: 0 },
            { x: 140, y: 100 },
        ]);
    });

    it('drops a candidate released on its own segment (a no-op insert)', () => {
        const released = [routed[0], { x: 101, y: 30 }, routed[1]];

        expect(normalizeOrthogonalWaypoints(source, released, target)).toEqual(routed);
    });

    it('leaves the bends of an orthogonal path alone, even around a jog of under 3 px', () => {
        const waypoints = [
            { x: 100, y: 0 },
            { x: 100, y: 2 },
            { x: 150, y: 2 },
            { x: 150, y: 100 },
        ];

        expect(normalizeOrthogonalWaypoints(source, waypoints, target)).toEqual(waypoints);
    });

    it('removes backtracks along one line', () => {
        const waypoints = [
            { x: 100, y: 0 },
            { x: 100, y: 160 }, // past the next point, then back up
            { x: 100, y: 100 },
            { x: 60, y: 100 }, // left, then right again into the target
        ];

        expect(normalizeOrthogonalWaypoints(source, waypoints, target)).toEqual(routed);
    });

    it('keeps a reversal next to a port when dropping it would turn the port leg around', () => {
        // Back along the source row: without (230, 0) the wire would leave the source leftwards.
        const waypoints = [
            { x: 230, y: 0 },
            { x: -20, y: 0 },
            { x: -20, y: 100 },
        ];

        expect(normalizeOrthogonalWaypoints({ x: 200, y: 0 }, waypoints, { x: 0, y: 100 })).toEqual(waypoints);
    });

    it('pushes a bend closer than a stub to its port out to 20 px', () => {
        const tooClose = [
            { x: 8, y: 0 },
            { x: 8, y: 100 },
        ];
        const leftOfTarget = [
            { x: 100, y: 0 },
            { x: 100, y: 60 },
            { x: 230, y: 60 }, // right of the target port: the wire would enter from the right
            { x: 230, y: 100 },
        ];

        expect(normalizeOrthogonalWaypoints(source, tooClose, target)).toEqual([
            { x: 20, y: 0 },
            { x: 20, y: 100 },
        ]);
        expect(normalizeOrthogonalWaypoints(source, leftOfTarget, target)).toEqual([
            { x: 100, y: 0 },
            { x: 100, y: 60 },
            { x: 180, y: 60 },
            { x: 180, y: 100 },
        ]);
    });

    it('moves the flow-8 riser dragged 75 px right', () => {
        // Flow 8 on the canvas: the riser's candidate inserted and dragged, as Foblex emitted it.
        const dragged = [
            { x: 2042.5, y: 470 },
            { x: 2117.7, y: 610 },
            { x: 2042.5, y: 750 },
        ];

        expect(normalizeOrthogonalWaypoints({ x: 1915, y: 470 }, dragged, { x: 2175, y: 750 })).toEqual([
            { x: 2117.7, y: 470 },
            { x: 2117.7, y: 750 },
        ]);
    });

    it('stops a riser dragged past the target at the target stub end', () => {
        // Flow 8 on the canvas: the same riser dragged a second time, past the target port's x.
        const dragged = [
            { x: 2117.7, y: 470 },
            { x: 2192.8, y: 610 },
            { x: 2117.7, y: 750 },
        ];

        expect(normalizeOrthogonalWaypoints({ x: 1915, y: 470 }, dragged, { x: 2175, y: 750 })).toEqual([
            { x: 2155, y: 470 },
            { x: 2155, y: 750 },
        ]);
    });

    function normalizedRoutes({ nodes, connections }: FlowFixture): Map<string, [IPoint[], IPoint[]]> {
        const nodesById = new Map(nodes.map((node) => [node.id, node]));
        const result = new Map<string, [IPoint[], IPoint[]]>();
        for (const [id, points] of routeAll(nodes, connections)) {
            const ends = resolveWireEnds(connections.find((connection) => connection.id === id)!, nodesById)!;
            const wireSource = getPortPosition(ends.sourceNode, ends.sourcePort);
            const wireTarget = getPortPosition(ends.targetNode, ends.targetPort);
            result.set(id, [points, normalizeOrthogonalWaypoints(wireSource, points, wireTarget)]);
        }
        return result;
    }

    it('leaves the router’s output unchanged (stacked pair, flow 8)', () => {
        for (const fixture of [stackedPair(), flow8()]) {
            const routes = normalizedRoutes(fixture);
            expect(routes.size).toBe(fixture.connections.length);
            for (const [id, [points, normalized]] of routes) {
                expect({ id, points: normalized }).toEqual({ id, points });
            }
        }
    });
});
