import { NodeType } from '@shared/models';

import { LayeredGraph } from './long-edges';
import { countCrossings, orderLayers } from './ordering';
import {
    connect,
    flow8,
    flow9,
    FlowFixture,
    layeredComponent,
    makeNode,
    tableNode,
    tableRowRole,
    withPorts,
} from './testing/fixtures';
import { randomGraph, shuffled } from './testing/random-graphs';

const CDT = NodeType.CLASSIFICATION_TABLE;

function fixture(nodes: ReturnType<typeof makeNode>[], connections: ReturnType<typeof connect>[]): FlowFixture {
    return { nodes: withPorts(nodes, connections), connections };
}

// The fewest crossings any order of the children can give, when every child has one input port:
// a wire pair crosses when its rows and its children are in opposite orders (brute force).
function fewestRowCrossings(layered: LayeredGraph, tableId: string): number {
    const rowsByChild = new Map<string, number[]>();
    for (const edge of layered.edges) {
        if (edge.source !== tableId || edge.sourceRow === null) continue;
        rowsByChild.set(edge.target, [...(rowsByChild.get(edge.target) ?? []), edge.sourceRow]);
    }
    const children = [...rowsByChild.values()];
    let fewest = Infinity;
    const permute = (order: number[][], rest: number[][]): void => {
        if (rest.length === 0) {
            let count = 0;
            for (let upper = 0; upper < order.length; upper++) {
                for (let lower = upper + 1; lower < order.length; lower++) {
                    for (const upperRow of order[upper])
                        for (const lowerRow of order[lower]) if (upperRow > lowerRow) count++;
                }
            }
            fewest = Math.min(fewest, count);
            return;
        }
        rest.forEach((child, index) => permute([...order, child], [...rest.slice(0, index), ...rest.slice(index + 1)]));
    };
    permute([], children);
    return fewest;
}

describe('orderLayers', () => {
    it('keeps table row order for the children, whatever the connection order and ids', () => {
        // Ids sort against the rows on purpose: z feeds from row 0, x from row 2.
        const nodes = [
            makeNode('s', NodeType.START),
            tableNode('t', CDT, 3),
            ...['z', 'y', 'x'].map((id) => makeNode(id, NodeType.PYTHON)),
        ];
        const connections = shuffled(
            [
                connect('in', 's', 'out', 't', 'table-in'),
                connect('r0', 't', tableRowRole(CDT, 0), 'z'),
                connect('r1', 't', tableRowRole(CDT, 1), 'y'),
                connect('r2', 't', tableRowRole(CDT, 2), 'x'),
            ],
            5
        );

        const order = orderLayers(layeredComponent(fixture(nodes, connections)));

        expect(order[2]).toEqual(['z', 'y', 'x']);
    });

    it('uncrosses a → d, b → c from the id order c, d', () => {
        const nodes = [
            makeNode('s', NodeType.START),
            ...['a', 'b', 'c', 'd'].map((id) => makeNode(id, NodeType.PYTHON)),
        ];
        const connections = [
            connect('sa', 's', 'out', 'a'),
            connect('sb', 's', 'out', 'b'),
            connect('ad', 'a', 'out', 'd'),
            connect('bc', 'b', 'out', 'c'),
        ];
        const layered = layeredComponent(fixture(nodes, connections));
        expect(countCrossings(layered, [['s'], ['a', 'b'], ['c', 'd']])).toBe(1);

        const order = orderLayers(layered);

        expect(order).toEqual([['s'], ['a', 'b'], ['d', 'c']]);
        expect(countCrossings(layered, order)).toBe(0);
    });

    it('is deterministic when the input arrays are shuffled', () => {
        for (const seed of [3, 17, 42]) {
            const { nodes, connections } = randomGraph(seed, { withTables: true });
            const expected = orderLayers(layeredComponent({ nodes, connections }));
            const reordered = orderLayers(
                layeredComponent({ nodes: shuffled(nodes, seed), connections: shuffled(connections, seed + 1) })
            );
            expect(reordered).toEqual(expected);
        }
    });

    it('orders flow 8 without a crossing', () => {
        const layered = layeredComponent(flow8());

        expect(countCrossings(layered, orderLayers(layered))).toBe(0);
    });

    it('orders flow 9 with the fewest row crossings any child order allows, a child at the median of its rows', () => {
        const cdt14 = 'f9-12-cdt14';
        const layered = layeredComponent(flow9());

        const order = orderLayers(layered);

        // Several rows feed each of Py#8, Py#4 and Py#7, interleaved: 11 is the floor.
        expect(countCrossings(layered, order)).toBe(fewestRowCrossings(layered, cdt14));
        expect(countCrossings(layered, order)).toBe(11);
        const children = order[layered.layerOf.get(cdt14)! + 1];
        const rank = (id: string): number => children.indexOf(id);
        const python4 = 'f9-01-py4'; // rows 3, 4, 7: median 4
        const python8 = 'f9-05-py8'; // rows 1, 6, 11: median 6
        const python9 = 'f9-03-py9'; // row 2
        const agent15 = 'f9-10-agent15'; // Default, row 10
        expect(rank(python9)).toBeLessThan(rank(python4));
        expect(rank(python4)).toBeLessThan(rank(python8));
        expect(rank(python8)).toBeLessThan(rank(agent15));
    });
});
