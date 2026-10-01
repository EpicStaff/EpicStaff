import { IPoint } from '@foblex/2d';
import { NodeType } from '@shared/models';

import { getPortPosition } from '../geometry/port-position';
import { computeLayout } from '../layout/compute-layout';
import { measure, QualityReport, wiresFromRoutes } from '../layout/quality/metrics';
import {
    connect,
    flow8,
    FlowFixture,
    makeNode,
    port,
    selfLoop,
    stackedPair,
    withPorts,
    withPositions,
} from '../layout/testing/fixtures';
import { randomGraph } from '../layout/testing/random-graphs';
import { ConnectionModel } from '../models/connection.model';
import { NodeModel } from '../models/node.model';
import { obstacleRect } from './obstacles';
import { routeAll } from './route-all';

function python(id: string, x: number, y: number): NodeModel {
    return makeNode(id, NodeType.PYTHON, { height: 60, position: { x, y } });
}

function wired(nodes: NodeModel[], connections: ConnectionModel[]): FlowFixture {
    return { nodes: withPorts(nodes, connections), connections };
}

function report({ nodes, connections }: FlowFixture, routes: Map<string, IPoint[]>): QualityReport {
    return measure(nodes, wiresFromRoutes(nodes, connections, routes, true));
}

function expectClean(result: QualityReport): void {
    const hardRules = [
        'wireThroughNode',
        'collinearOverlaps',
        'selfIntersections',
        'badStubs',
        'stackedGapViolations',
        'shortSegments',
    ] as const;
    expect(Object.fromEntries(hardRules.map((rule) => [rule, result[rule]]))).toEqual(
        Object.fromEntries(hardRules.map((rule) => [rule, 0]))
    );
}

function verticalXs(points: IPoint[]): number[] {
    return points.slice(1).flatMap((point, index) => (point.x === points[index].x ? [point.x] : []));
}

function horizontalYs(points: IPoint[]): number[] {
    return points.slice(1).flatMap((point, index) => (point.y === points[index].y ? [point.y] : []));
}

// Deterministic Fisher–Yates driven by the fixtures' LCG, so the shuffle itself is reproducible.
function shuffled<T>(items: T[], seed: number): T[] {
    const copy = [...items];
    let state = seed;
    for (let index = copy.length - 1; index > 0; index--) {
        state = (Math.imul(state, 1103515245) + 12345) & 0x7fffffff;
        const other = state % (index + 1);
        [copy[index], copy[other]] = [copy[other], copy[index]];
    }
    return copy;
}

describe('routeAll', () => {
    it('returns interior points only, and none for a straight wire', () => {
        const fixture = wired([python('a', 0, 0), python('b', 600, 0)], [connect('w', 'a', 'out', 'b', 'in')]);

        expect(routeAll(fixture.nodes, fixture.connections)).toEqual(new Map([['w', []]]));
    });

    it('routes the stacked pair #14→#15 through the gap with 4 bends', () => {
        const fixture = stackedPair();

        const routes = routeAll(fixture.nodes, fixture.connections);

        const result = report(fixture, routes);
        expectClean(result);
        expect(result.bends).toBe(4);
    });

    it('routes a stacked pair only 20 px apart through the gap, 10 px from each node', () => {
        // Py14 0..60, Py15 80..140: the return leg runs on y 70, the one line clear of both.
        const fixture = stackedPair(80);

        const routes = routeAll(fixture.nodes, fixture.connections);

        expectClean(report(fixture, routes));
        expect(routes.get('c14-15')).toEqual([
            { x: 355, y: 30 },
            { x: 355, y: 70 },
            { x: -25, y: 70 },
            { x: -25, y: 110 },
        ]);
    });

    it("doesn't turn off its start row where another wire's first or last segment carries on (seed 770)", () => {
        // Arranged 20 px apart, a long wire runs over an agent on the squeezed line under a table and
        // drops into the next node on the agent's output row, while the agent's own wire has to rise
        // to that line: turning at the other wire's last segment pinned both risers to one column.
        const { nodes, connections } = randomGraph(770, { withTables: true });
        const placed = withPositions(nodes, computeLayout(nodes, connections));

        expectClean(report({ nodes: placed, connections }, routeAll(placed, connections)));
    });

    // A wire returning to a node on its left (x-ranges apart) goes over the top of both nodes,
    // never under: up from the source stub, left above both tops, down into the target stub.
    describe('a return wire goes over the top of both nodes', () => {
        // The legs between the stubs: the waypoints leave the two port points out.
        function legsAbove(points: IPoint[], limit: number): boolean {
            const legs = horizontalYs(points);
            return legs.length > 0 && legs.every((y) => y <= limit);
        }

        it('#16 (right) → #15 (left) on one row', () => {
            const fixture = wired(
                [python('py15', 0, 0), python('py16', 600, 0)],
                [connect('w', 'py16', 'out', 'py15', 'in')]
            );

            const routes = routeAll(fixture.nodes, fixture.connections);

            const result = report(fixture, routes);
            expectClean(result);
            expect(result.bends).toBe(4);
            const top = Math.min(...fixture.nodes.map((node) => obstacleRect(node).top));
            expect(legsAbove(routes.get('w')!, top)).toBe(true);
        });

        it('stays above both tops even when a taller node between them makes going under shorter', () => {
            // Under the blocker is 185 px down and up; over it is 245: the rule wins over length.
            const blocker = makeNode('blocker', NodeType.PYTHON, { height: 400, position: { x: 600, y: 0 } });
            const fixture = wired(
                [python('py15', 0, 200), blocker, python('py16', 1200, 200)],
                [connect('w', 'py16', 'out', 'py15', 'in')]
            );

            const routes = routeAll(fixture.nodes, fixture.connections);

            expectClean(report(fixture, routes));
            const endpointsTop = Math.min(obstacleRect(fixture.nodes[0]).top, obstacleRect(fixture.nodes[2]).top);
            expect(legsAbove(routes.get('w')!, endpointsTop)).toBe(true);
        });

        it('#5 → #7: lower right source, upper left target, the leg above the upper one', () => {
            const fixture = wired(
                [python('py7', 440, 180), python('py5', 2800, 480)],
                [connect('w', 'py5', 'out', 'py7', 'in')]
            );

            const routes = routeAll(fixture.nodes, fixture.connections);

            expectClean(report(fixture, routes));
            expect(legsAbove(routes.get('w')!, obstacleRect(fixture.nodes[0]).top)).toBe(true);
        });
    });

    it('skips stale connections without throwing', () => {
        const nodes = withPorts([python('a', 0, 0), python('b', 600, 0)], [connect('ok', 'a', 'out', 'b', 'in')]);
        const connections = [
            connect('ok', 'a', 'out', 'b', 'in'),
            connect('missing-node', 'a', 'out', 'ghost', 'in'),
            connect('missing-port', 'a', 'nowhere', 'b', 'in'),
        ];

        const routes = routeAll(nodes, connections);

        expect([...routes.keys()]).toEqual(['ok']);
    });

    it('leaves a user-adjusted wire out of the result but keeps others off its corridor', () => {
        const free = wired([python('a', 0, 0), python('b', 800, 300)], [connect('w', 'a', 'out', 'b', 'in')]);
        const [riserX] = verticalXs(routeAll(free.nodes, free.connections).get('w')!);
        // c → d is hand-drawn with its riser on exactly the line the free route takes.
        const frozen: ConnectionModel = {
            ...connect('frozen', 'c', 'out', 'd', 'in'),
            userAdjustedWaypoints: true,
            waypoints: [
                { x: riserX, y: -270 },
                { x: riserX, y: 630 },
            ],
        };
        const fixture = wired(
            [python('a', 0, 0), python('b', 800, 300), python('c', -700, -300), python('d', 1400, 600)],
            [connect('w', 'a', 'out', 'b', 'in'), frozen]
        );

        const routes = routeAll(fixture.nodes, fixture.connections);

        expect([...routes.keys()]).toEqual(['w']);
        const withFrozen = new Map(routes).set('frozen', frozen.waypoints!);
        expect(verticalXs(routes.get('w')!)).not.toContain(riserX);
        expect(report(fixture, withFrozen).collinearOverlaps).toBe(0);
    });

    it('leaves connections on top/bottom ports out of the result', () => {
        const tool = makeNode('tool', NodeType.TOOL, {
            height: 60,
            position: { x: 0, y: 300 },
            ports: [port('tool', 'tool-top', 'top')],
        });
        const nodes = [
            ...withPorts([python('a', 0, 0), python('b', 600, 0)], [connect('w', 'a', 'out', 'b', 'in')]),
            tool,
        ];
        const connections = [connect('w', 'a', 'out', 'b', 'in'), connect('t', 'a', 'out', 'tool', 'tool-top')];

        expect([...routeAll(nodes, connections).keys()]).toEqual(['w']);
    });

    it('routes around an EDGE node’s fixed collision box', () => {
        // The EDGE box (308×196 at offset 5, -12) sits across the straight line a → b.
        const edge = makeNode('edge', NodeType.EDGE, { position: { x: 500, y: -60 } });
        const fixture = wired([python('a', 0, 0), edge, python('b', 1100, 0)], [connect('w', 'a', 'out', 'b', 'in')]);

        const routes = routeAll(fixture.nodes, fixture.connections);

        const result = report(fixture, routes);
        expectClean(result);
        expect(result.straightAdjacent).toBe(0);
        const box = obstacleRect(edge);
        // Every horizontal leg between the stubs passes above or below the box.
        expect(horizontalYs(routes.get('w')!).every((y) => y <= box.top || y >= box.bottom)).toBe(true);
    });

    it('routes a self-loop out east, around the node and in from the west', () => {
        const fixture = selfLoop();

        const routes = routeAll(fixture.nodes, fixture.connections);

        const result = report(fixture, routes);
        expectClean(result);
        expect(result.bends).toBe(4);
        const loop = fixture.nodes.find((node) => node.id === 'loop')!;
        const box = obstacleRect(loop);
        const legs = routes.get('c2')!.filter((point) => point.y !== loop.position.y + 30);
        expect(legs.length).toBe(2);
        expect(legs.every((point) => point.y >= box.bottom)).toBe(true); // below the node
    });

    it('returns a route for every wire when nodes overlap, the fallback shape if need be, without throwing', () => {
        const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
        // `b` sits on top of `c`, so b's input stub ends inside c's padded box, and `a`'s stub inside `a2`.
        const fixture = wired(
            [python('a', 0, 0), python('a2', 340, 0), python('b', 900, 300), python('c', 890, 290)],
            [
                connect('ab', 'a', 'out', 'b', 'in'),
                connect('ac', 'a', 'out', 'c', 'in'),
                connect('a2b', 'a2', 'out', 'b', 'in'),
            ]
        );

        const first = routeAll(fixture.nodes, fixture.connections);
        const second = routeAll(fixture.nodes, fixture.connections);

        expect([...first.keys()].sort()).toEqual(['a2b', 'ab', 'ac']);
        expect(second).toEqual(first);
        const warnedIds = warn.mock.calls.map(([message]) => String(message));
        expect(new Set(warnedIds).size).toBe(warnedIds.length); // at most once per connection id
        warn.mockRestore();
    });

    it('gives identical routes when nodes and connections are shuffled', () => {
        const { nodes, connections } = flow8();

        const reference = routeAll(nodes, connections);

        for (const seed of [1, 2, 3]) {
            const again = routeAll(shuffled(nodes, seed), shuffled(connections, seed + 10));
            expect([...again.entries()].sort(([first], [second]) => (first < second ? -1 : 1))).toEqual(
                [...reference.entries()].sort(([first], [second]) => (first < second ? -1 : 1))
            );
        }
    });

    it('starts and ends every route at the stubs of the ports getPortPosition gives', () => {
        const fixture = flow8();
        const byId = new Map(fixture.nodes.map((node) => [node.id, node]));

        const routes = routeAll(fixture.nodes, fixture.connections);

        for (const connection of fixture.connections) {
            const points = routes.get(connection.id)!;
            if (points.length === 0) continue;
            const sourceNode = byId.get(connection.sourceNodeId)!;
            const targetNode = byId.get(connection.targetNodeId)!;
            const source = getPortPosition(
                sourceNode,
                sourceNode.ports!.find((candidate) => candidate.id === connection.sourcePortId)
            );
            const target = getPortPosition(
                targetNode,
                targetNode.ports!.find((candidate) => candidate.id === connection.targetPortId)
            );
            expect(points[0].y).toBe(source.y);
            expect(points[points.length - 1].y).toBe(target.y);
        }
    });
});
