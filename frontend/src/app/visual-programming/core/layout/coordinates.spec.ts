import { NodeType } from '@shared/models';

import { DecisionTableNodeModel, NodeModel } from '../models/node.model';
import { assignTops } from './coordinates';
import { LayoutEdge } from './layout-graph';
import { LayeredGraph } from './long-edges';
import { orderLayers } from './ordering';
import {
    connect,
    FlowFixture,
    layeredComponent,
    makeNode,
    tableNode,
    tableRowRole,
    withPorts,
} from './testing/fixtures';
import { randomGraph } from './testing/random-graphs';

const TABLE = NodeType.TABLE;
const GRID = 20;

interface Placed {
    layered: LayeredGraph;
    order: string[][];
    tops: Map<string, number>;
}

function place(fixture: FlowFixture): Placed {
    const layered = layeredComponent(fixture);
    const order = orderLayers(layered);
    return { layered, order, tops: assignTops(layered, order, 100) };
}

function wired(nodes: NodeModel[], connections: ReturnType<typeof connect>[]): FlowFixture {
    return { nodes: withPorts(nodes, connections), connections };
}

const sourcePortY = ({ tops }: Placed, edge: LayoutEdge): number => tops.get(edge.source)! + edge.sourceOffsetY;
const targetPortY = ({ tops }: Placed, edge: LayoutEdge): number => tops.get(edge.target)! + edge.targetOffsetY;
const edge = ({ layered }: Placed, id: string): LayoutEdge => layered.edges.find((candidate) => candidate.id === id)!;
const python = (id: string, height = 60): NodeModel => makeNode(id, NodeType.PYTHON, { height });

describe('assignTops', () => {
    it("puts a table's row children straight on their rows", () => {
        const connections = [
            connect('in', 's', 'out', 't', 'table-in'),
            ...[0, 1, 2].map((row) => connect(`r${row}`, 't', tableRowRole(TABLE, row), `c${row}`)),
        ];
        const placed = place(
            wired(
                [
                    makeNode('s', NodeType.START, { height: 60 }),
                    tableNode('t', TABLE, 3),
                    ...['c0', 'c1', 'c2'].map((id) => python(id)),
                ],
                connections
            )
        );

        for (const id of ['in', 'r0', 'r1', 'r2']) {
            expect(targetPortY(placed, edge(placed, id))).toBe(sourcePortY(placed, edge(placed, id)));
        }
        // Consecutive-row siblings touch (the straight-rows exception to no node overlap).
        expect(placed.tops.get('c1')).toBe(placed.tops.get('c0')! + 60);
    });

    it.each([
        [['a', 'b'], 'centres a merge of two feeding ports between them'],
        [['a', 'b', 'c'], 'puts a merge of three straight on the middle one'],
    ])('%j: %s', (parents) => {
        const connections = [
            ...parents.map((id) => connect(`s${id}`, 's', 'out', id)),
            ...parents.map((id) => connect(`${id}m`, id, 'out', 'm')),
        ];
        const placed = place(
            wired([makeNode('s', NodeType.START), ...[...parents, 'm'].map((id) => python(id))], connections)
        );

        const ports = parents.map((id) => placed.tops.get(id)! + 30).sort((first, second) => first - second);
        const middle = ports.length % 2 === 1 ? ports[1] : (ports[0] + ports[1]) / 2;
        expect(ports[ports.length - 1] - ports[0]).toBeGreaterThan(0);
        expect(placed.tops.get('m')! + 30).toBe(middle);
    });

    it('lets a higher-priority node push a lower one, keeping the order and the gap', () => {
        // Both are row children; p also feeds x, so p outranks q. q (400 tall) can't sit on its row
        // under p, so q is the one that gives way.
        const connections = [
            connect('in', 's', 'out', 't', 'table-in'),
            connect('rp', 't', tableRowRole(TABLE, 0), 'p'),
            connect('rq', 't', tableRowRole(TABLE, 1), 'q'),
            connect('px', 'p', 'out', 'x'),
        ];
        const placed = place(
            wired(
                [makeNode('s', NodeType.START), tableNode('t', TABLE, 2), python('p'), python('q', 400), python('x')],
                connections
            )
        );

        expect(targetPortY(placed, edge(placed, 'rp'))).toBe(sourcePortY(placed, edge(placed, 'rp')));
        expect(placed.tops.get('q')!).toBeGreaterThanOrEqual(placed.tops.get('p')! + 60 + 20);
        expect(placed.order[2]).toEqual(['p', 'q']);
    });

    it('stacks siblings that cannot all be straight 20 px apart: pitch = height + 20', () => {
        const connections = ['a', 'b', 'c'].map((id) => connect(`s${id}`, 's', 'out', id));
        const placed = place(
            wired([makeNode('s', NodeType.START), python('a'), python('b'), python('c')], connections)
        );

        expect(placed.order[1]).toEqual(['a', 'b', 'c']);
        expect(placed.tops.get('b')! - placed.tops.get('a')!).toBe(80);
        expect(placed.tops.get('c')! - placed.tops.get('b')!).toBe(80);
    });

    it('keeps 20 between real nodes, 20 next to a dummy and 10 between dummies; only straight row siblings touch', () => {
        for (let seed = 1; seed <= 60; seed++) {
            const { layered, order, tops } = place(randomGraph(seed, { withTables: seed % 2 === 0 }));
            const straightRow = (child: string): Set<string> =>
                new Set(
                    layered.edges
                        .filter((candidate) => candidate.target === child && candidate.sourceRow !== null)
                        .filter(
                            (candidate) =>
                                tops.get(candidate.source)! + candidate.sourceOffsetY ===
                                tops.get(child)! + candidate.targetOffsetY
                        )
                        .map((candidate) => `${candidate.source}:${candidate.sourceRow}`)
                );
            for (const layer of order) {
                for (let position = 1; position < layer.length; position++) {
                    const [upper, lower] = [layer[position - 1], layer[position]];
                    const gap = tops.get(lower)! - (tops.get(upper)! + layered.nodes.get(upper)!.height);
                    const dummies = [upper, lower].filter((id) => layered.nodes.get(id)!.isDummy).length;
                    const upperRows = [...straightRow(upper)];
                    const touchingAllowed = [...straightRow(lower)].some((slot) => {
                        const [table, row] = slot.split(':');
                        return upperRows.includes(`${table}:${Number(row) - 1}`);
                    });
                    const minimum = dummies === 2 ? 10 : dummies === 1 ? 20 : touchingAllowed ? 0 : 20;
                    expect({ seed, upper, lower, ok: gap >= minimum - 1e-6 }).toEqual({ seed, upper, lower, ok: true });
                }
            }
        }
    });

    it('keeps every real top on the 20-px grid unless that makes an input wire straight or centres it', () => {
        for (let seed = 1; seed <= 60; seed++) {
            const { layered, tops } = place(randomGraph(seed, { withTables: seed % 2 === 1 }));
            const originY = (incoming: LayoutEdge): number => {
                const origin = layered.dummyOrigins.get(incoming.source) ?? incoming;
                return tops.get(origin.source)! + origin.sourceOffsetY;
            };
            for (const [id, node] of layered.nodes) {
                const top = tops.get(id)!;
                if (node.isDummy || top % GRID === 0) continue;
                const incoming = layered.edges.filter((candidate) => candidate.target === id);
                const inputY = top + (incoming[0]?.targetOffsetY ?? 0);
                const ys = incoming.map(originY).sort((a, b) => a - b);
                const middle = Math.floor(ys.length / 2);
                const medianY = ys.length % 2 === 1 ? ys[middle] : (ys[middle - 1] + ys[middle]) / 2;
                expect({ seed, id, exempt: ys.includes(inputY) || inputY === medianY }).toEqual({
                    seed,
                    id,
                    exempt: true,
                });
            }
        }
    });

    it("moves the next sibling when a table's rows change but size.height doesn't", () => {
        const connections = [connect('st', 's', 'out', 't', 'table-in'), connect('su', 's', 'out', 'under')];
        const twoRows = tableNode('t', TABLE, 2);
        const fourRows = tableNode('t', TABLE, 4);
        const grown: NodeModel = {
            ...twoRows,
            ports: fourRows.ports,
            data: (fourRows as DecisionTableNodeModel).data,
        } as NodeModel;
        const nodes = (table: NodeModel): NodeModel[] => [makeNode('s', NodeType.START), table, python('under')];

        // `under` sorts after `t` (same parent port, ties by id), so it is the sibling below the table.
        const before = place(wired(nodes(twoRows), connections));
        const after = place(wired(nodes(grown), connections));

        const gap = (placed: Placed): number =>
            placed.tops.get('under')! - (placed.tops.get('t')! + placed.layered.nodes.get('t')!.height);
        expect(after.layered.nodes.get('t')!.height).toBe(twoRows.size.height + 120);
        expect(gap(before)).toBeGreaterThanOrEqual(20);
        expect(gap(after)).toBeGreaterThanOrEqual(20);
        expect(after.tops.get('under')! - after.tops.get('t')!).toBeGreaterThan(
            before.tops.get('under')! - before.tops.get('t')!
        );
    });
});
