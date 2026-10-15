import { IPoint } from '@foblex/2d';
import { NodeType } from '@shared/models';

import { getPortPosition } from '../geometry/port-position';
import { measure, QualityReport, RoutedWire } from '../layout/quality/metrics';
import { connect, makeNode, stackedPair, withPorts } from '../layout/testing/fixtures';
import { NodeModel } from '../models/node.model';
import { obstacleRect, Rect } from './obstacles';
import { findRoute, SegmentIndex } from './path-search';
import { buildRoutingGrid } from './routing-grid';

const STUB = 20;
const OWN_PORTS = { source: 'a_out', target: 'b_in' };

interface Scene {
    nodes: NodeModel[];
    source: IPoint;
    target: IPoint;
}

function python(id: string, x: number, y: number): NodeModel {
    return makeNode(id, NodeType.PYTHON, { height: 60, position: { x, y } });
}

// Nodes `a` → `b` plus any bystanders; ports from getPortPosition, as the router will use them.
function scene(nodes: NodeModel[]): Scene {
    const wired = withPorts(nodes, [connect('w', 'a', 'out', 'b', 'in')]);
    const portOf = (nodeId: string, portId: string): IPoint => {
        const node = wired.find((candidate) => candidate.id === nodeId)!;
        return getPortPosition(
            node,
            node.ports!.find((candidate) => candidate.id === portId)
        );
    };
    return { nodes: wired, source: portOf('a', 'a_out'), target: portOf('b', 'b_in') };
}

function route(
    { nodes, source, target }: Scene,
    occupied = new SegmentIndex(),
    extraObstacles: Rect[] = []
): IPoint[] | null {
    const start = { x: source.x + STUB, y: source.y };
    const goal = { x: target.x - STUB, y: target.y };
    const grid = buildRoutingGrid(
        [...nodes.map(obstacleRect), ...extraObstacles],
        [start.x, goal.x],
        [start.y, goal.y]
    );
    return findRoute(grid, start, goal, occupied, OWN_PORTS);
}

function wire(id: string, points: IPoint[], sourceNodeId = 'a', targetNodeId = 'b'): RoutedWire {
    return { id, sourcePortKey: `${id}_out`, targetPortKey: `${id}_in`, sourceNodeId, targetNodeId, points };
}

function measureRoute(built: Scene, interior: IPoint[], others: RoutedWire[] = []): QualityReport {
    return measure(built.nodes, [wire('w', [built.source, ...interior, built.target]), ...others]);
}

function stackedScene(targetTop: number): Scene {
    const { nodes } = stackedPair(targetTop);
    const renamed = nodes.map((node) => ({ ...node, id: node.id === 'py14' ? 'a' : 'b', ports: [] }));
    return scene(renamed);
}

function lengthOf(points: IPoint[]): number {
    return points
        .slice(1)
        .reduce(
            (total, point, index) => total + Math.abs(point.x - points[index].x) + Math.abs(point.y - points[index].y),
            0
        );
}

describe('findRoute', () => {
    it('runs straight east on the same row with nothing in between', () => {
        const built = scene([python('a', 0, 0), python('b', 600, 0)]);

        expect(route(built)).toEqual([
            { x: 355, y: 30 },
            { x: 575, y: 30 },
        ]);
    });

    it('goes around an obstacle in the way without entering it', () => {
        const built = scene([python('a', 0, 0), python('blocker', 500, 0), python('b', 1000, 0)]);

        const points = route(built)!;
        const report = measureRoute(built, points);

        expect(points).not.toBeNull();
        expect(report.wireThroughNode).toBe(0);
        expect(report.badStubs).toBe(0);
        expect(report.selfIntersections).toBe(0);
    });

    it('routes the stacked pair (60-px gap) through the gap with 4 bends', () => {
        const built = stackedScene(120);

        const points = route(built)!;
        const report = measureRoute(built, points);

        expect(report.bends).toBe(4);
        expect(report.stackedGapViolations).toBe(0);
        expect(report.wireThroughNode).toBe(0);
        const returnLeg = points.find((point, index) => index > 0 && point.y === points[index - 1].y);
        expect(returnLeg!.y).toBe(90); // the middle of the gap between py14 (bottom 60) and py15 (top 120)
    });

    it('routes a stacked pair with a 40-px gap through the gap', () => {
        const built = stackedScene(100);

        const points = route(built)!;
        const report = measureRoute(built, points);

        // The padded boxes leave 70..90 free; the leg takes its midline.
        expect(points.some((point, index) => index > 0 && point.y === 80 && points[index - 1].y === 80)).toBe(true);
        expect(report.bends).toBe(4);
        expect(report.stackedGapViolations).toBe(0);
        expect(report.wireThroughNode).toBe(0);
    });

    it('goes around a stacked pair with only a 10-px gap', () => {
        const built = stackedScene(70);

        const points = route(built)!;
        const report = measureRoute(built, points);

        expect(points).not.toBeNull();
        expect(report.bends).toBe(4);
        expect(report.wireThroughNode).toBe(0);
        expect(report.badStubs).toBe(0);
        const horizontals = points.filter((point, index) => index > 0 && point.y === points[index - 1].y);
        // Around a padded box, on or outside its edge (py14 top −10, py15 bottom 140).
        expect(horizontals.every((point) => point.y <= -10 || point.y >= 140)).toBe(true);
    });

    it('takes an equally cheap route that avoids crossing an occupied wire', () => {
        const built = scene([python('a', 0, 0), python('b', 800, 300)]);
        const free = route(built)!;
        const riserIndex = free.findIndex((point, index) => index > 0 && point.x === free[index - 1].x);
        const riserX = free[riserIndex].x;
        // A short horizontal wire across that riser only.
        const occupiedWire = wire('other', [
            { x: riserX - 5, y: 180 },
            { x: riserX + 5, y: 180 },
        ]);
        const occupied = new SegmentIndex();
        occupied.add(occupiedWire);

        const avoiding = route(built, occupied)!;

        const freeReport = measureRoute(built, free, [occupiedWire]);
        const avoidingReport = measureRoute(built, avoiding, [occupiedWire]);
        expect(freeReport.crossings).toBe(1);
        expect(avoidingReport.crossings).toBe(0);
        expect(avoidingReport.bends).toBe(freeReport.bends);
        expect(lengthOf(avoiding)).toBe(lengthOf(free));
    });

    it('keeps a straight route across a short wire, because a detour costs more than the crossing', () => {
        const built = scene([python('a', 0, 0), python('b', 600, 0)]);
        const occupiedWire = wire('other', [
            { x: 465, y: 0 },
            { x: 465, y: 60 },
        ]);
        const occupied = new SegmentIndex();
        occupied.add(occupiedWire);

        const points = route(built, occupied)!;

        expect(points.length).toBe(2);
        expect(measureRoute(built, points, [occupiedWire]).crossings).toBe(1);
    });

    it('returns null when the goal is enclosed', () => {
        const built = scene([python('a', 0, 0), python('b', 800, 0)]);
        const goal = { x: built.target.x - STUB, y: built.target.y };
        const ring: Rect[] = [
            { left: goal.x - 100, top: goal.y - 100, right: goal.x + 100, bottom: goal.y - 60 },
            { left: goal.x - 100, top: goal.y + 60, right: goal.x + 100, bottom: goal.y + 100 },
            { left: goal.x - 100, top: goal.y - 100, right: goal.x - 60, bottom: goal.y + 100 },
            { left: goal.x + 60, top: goal.y - 100, right: goal.x + 100, bottom: goal.y + 100 },
        ];

        expect(route(built, new SegmentIndex(), ring)).toBeNull();
    });

    it('escapes when the start stub ends inside another node', () => {
        // `overlap` sits on top of a's right edge, so a's stub end is inside its padded box.
        const built = scene([python('a', 0, 0), python('overlap', 340, 0), python('b', 1200, 300)]);

        const points = route(built);

        expect(points).not.toBeNull();
        expect(points![0]).toEqual({ x: 355, y: 30 });
        expect(points![points!.length - 1]).toEqual({ x: 1175, y: 330 });
    });

    it('never runs through its own stub, even along the padding edge between port and stub end', () => {
        // a's padded right edge (x 345) lies between its port (335) and stub end (355). Two nodes
        // stacked tight on a close the rows above it, and the column at x 355 is taken all the way
        // up, so running north along 345, across the own stub, would be the cheapest way to b.
        const built = scene([python('a', 0, 0), python('c', 0, -80), python('c2', 0, -160), python('b', -800, -1200)]);
        const other = wire('other', [
            { x: 355, y: -1500 },
            { x: 355, y: 20 },
        ]);
        const occupied = new SegmentIndex();
        occupied.add(other);

        const points = route(built, occupied)!;

        expect(measureRoute(built, points, [other]).selfIntersections).toBe(0);
        expect(measureRoute(built, points, [other]).wireThroughNode).toBe(0);
    });

    it('keeps to the given rows, so a stacked pair returns through the gap even when crossings make the top cheaper', () => {
        const built = stackedScene(120);
        const occupied = new SegmentIndex();
        // Five risers span the whole gap (y 60..120) between the two nodes' input and output columns.
        const risers = [60, 120, 180, 240, 300].map((x) =>
            wire(`riser${x}`, [
                { x, y: 60 },
                { x, y: 120 },
            ])
        );
        risers.forEach((riser) => occupied.add(riser));
        const start = { x: built.source.x + STUB, y: built.source.y };
        const goal = { x: built.target.x - STUB, y: built.target.y };
        const grid = buildRoutingGrid(
            built.nodes.map(obstacleRect),
            [start.x, goal.x, 60, 120, 180, 240, 300],
            [start.y, goal.y, 60, 120]
        );
        const legs = (points: IPoint[]): number[] =>
            points.slice(1).flatMap((point, index) => (point.y === points[index].y ? [point.y] : []));

        const free = findRoute(grid, start, goal, occupied, OWN_PORTS)!;
        const banded = findRoute(grid, start, goal, occupied, OWN_PORTS, { rows: { top: 0, bottom: 180 } })!;

        expect(legs(free).some((y) => y < 0 || y > 180)).toBe(true);
        expect(legs(banded).every((y) => y >= 0 && y <= 180)).toBe(true);
        expect(measureRoute(built, banded, risers).stackedGapViolations).toBe(0);
    });

    it('gives the same route on repeated runs', () => {
        const built = scene([python('a', 0, 0), python('blocker', 500, 100), python('b', 1000, 300)]);
        const occupied = new SegmentIndex();
        occupied.add(
            wire('other', [
                { x: 400, y: -100 },
                { x: 400, y: 500 },
            ])
        );

        expect(route(built, occupied)).toEqual(route(built, occupied));
    });
});

describe('SegmentIndex', () => {
    const ownPorts = { source: 'mine_out', target: 'mine_in' };

    it('counts perpendicular crossings of other wires and ignores wires sharing a port', () => {
        const index = new SegmentIndex();
        index.add(
            wire('other', [
                { x: 50, y: -100 },
                { x: 50, y: 100 },
            ])
        );
        index.add({
            id: 'sibling',
            sourcePortKey: 'mine_out',
            targetPortKey: 'x_in',
            points: [
                { x: 70, y: -100 },
                { x: 70, y: 100 },
            ],
        });

        expect(index.crossings({ x: 0, y: 0 }, { x: 100, y: 0 }, ownPorts)).toBe(1);
        expect(index.crossings({ x: 0, y: 200 }, { x: 100, y: 200 }, ownPorts)).toBe(0);
    });

    it('measures collinear overlap with other wires only', () => {
        const index = new SegmentIndex();
        index.add(
            wire('other', [
                { x: 0, y: 40 },
                { x: 100, y: 40 },
            ])
        );
        index.add({
            id: 'trunk',
            sourcePortKey: 'y_out',
            targetPortKey: 'mine_in',
            points: [
                { x: 0, y: 40 },
                { x: 100, y: 40 },
            ],
        });

        expect(index.sharedLength({ x: 60, y: 40 }, { x: 160, y: 40 }, ownPorts)).toBe(40);
        expect(index.sharedLength({ x: 60, y: 41 }, { x: 160, y: 41 }, ownPorts)).toBe(0);
    });

    it('holds the same penalties in its grid arrays as crossings/sharedLength give, trunk withdrawn or not', () => {
        const grid = buildRoutingGrid(
            [
                { left: 0, top: 0, right: 100, bottom: 60 },
                { left: 300, top: 200, right: 400, bottom: 260 },
            ],
            [20, 150, 250, 420],
            [30, 120, 230, 300]
        );
        const index = new SegmentIndex();
        // On-grid wires, a frozen off-grid one (x 137, y 77) with a diagonal pair, and a trunk sibling.
        index.add(
            wire('a', [
                { x: 20, y: 30 },
                { x: 150, y: 30 },
                { x: 150, y: 230 },
                { x: 420, y: 230 },
            ])
        );
        index.add(
            wire('frozen', [
                { x: -20, y: 77 },
                { x: 137, y: 77 },
                { x: 250, y: 290 },
                { x: 250, y: 300 },
            ])
        );
        index.add({
            ...wire('sibling', [
                { x: 100, y: 120 },
                { x: 420, y: 120 },
            ]),
            sourcePortKey: 'mine_out',
        });
        const penalties = index.penaltiesFor(grid);
        const { xs, ys } = grid;
        const columns = xs.length;

        const mismatches = (ports: { source: string; target: string }): string[] => {
            const found: string[] = [];
            for (let yi = 0; yi < ys.length; yi++) {
                for (let xi = 0; xi < xs.length; xi++) {
                    const cell = yi * columns + xi;
                    if (xi + 1 < xs.length) {
                        const [left, right] = [
                            { x: xs[xi], y: ys[yi] },
                            { x: xs[xi + 1], y: ys[yi] },
                        ];
                        const east = penalties.verticalThrough[cell + 1] + penalties.horizontalStepCrossings[cell];
                        const west = penalties.verticalThrough[cell] + penalties.horizontalStepCrossings[cell];
                        if (east !== index.crossings(left, right, ports)) found.push(`east ${xi},${yi}`);
                        if (west !== index.crossings(right, left, ports)) found.push(`west ${xi},${yi}`);
                        if (penalties.horizontalShared[cell] !== index.sharedLength(left, right, ports)) {
                            found.push(`shared h ${xi},${yi}`);
                        }
                    }
                    if (yi + 1 < ys.length) {
                        const [upper, lower] = [
                            { x: xs[xi], y: ys[yi] },
                            { x: xs[xi], y: ys[yi + 1] },
                        ];
                        const south =
                            penalties.horizontalThrough[cell + columns] + penalties.verticalStepCrossings[cell];
                        const north = penalties.horizontalThrough[cell] + penalties.verticalStepCrossings[cell];
                        if (south !== index.crossings(upper, lower, ports)) found.push(`south ${xi},${yi}`);
                        if (north !== index.crossings(lower, upper, ports)) found.push(`north ${xi},${yi}`);
                        if (penalties.verticalShared[cell] !== index.sharedLength(upper, lower, ports)) {
                            found.push(`shared v ${xi},${yi}`);
                        }
                    }
                }
            }
            return found;
        };

        expect(mismatches({ source: 'nobody_out', target: 'nobody_in' })).toEqual([]);
        const trunk = index.trunkOf(ownPorts);
        expect(trunk.length).toBe(1);
        for (const sibling of trunk) penalties.draw(sibling.points, -1);
        expect(mismatches(ownPorts)).toEqual([]);
        // The reference really sees the frozen wire's crossings and the sibling's shared run.
        expect(index.crossings({ x: 150, y: 77 - 47 }, { x: 150, y: 120 }, ownPorts)).toBeGreaterThan(0);
        expect(index.sharedLength({ x: 150, y: 120 }, { x: 250, y: 120 }, { source: 'x', target: 'y' })).toBe(100);
    });
});
