import { NodeType } from '@shared/models';

import { assignLefts } from './columns';
import { assignTops } from './coordinates';
import { LayoutEdge, LayoutNode } from './layout-graph';
import { LayeredGraph } from './long-edges';
import { orderLayers } from './ordering';
import { connect, layeredComponent, makeNode, tableNode, tableRowRole, withPorts } from './testing/fixtures';

function box(id: string, options: Partial<LayoutNode> = {}): LayoutNode {
    return {
        id,
        width: 330,
        height: 60,
        inputOffsetY: 30,
        isTrigger: false,
        isTable: false,
        isDummy: false,
        hasSelfLoop: false,
        ...options,
    };
}

function wire(source: string, target: string): LayoutEdge {
    return {
        id: `${source}->${target}`,
        source,
        target,
        sourceOffsetY: 30,
        targetOffsetY: 30,
        fromTableRow: false,
        sourceRow: null,
    };
}

// Two layers, hand-placed: `sources` in layer 0 and `targets` in layer 1, at the given tops.
function twoLayers(tops: Record<string, number>, sources: string[], targets: string[], edges: LayoutEdge[]) {
    const layered: LayeredGraph = {
        nodes: new Map([...sources, ...targets].map((id) => [id, box(id)])),
        edges,
        layerOf: new Map([
            ...sources.map((id): [string, number] => [id, 0]),
            ...targets.map((id): [string, number] => [id, 1]),
        ]),
        backEdges: [],
        dummyOrigins: new Map(),
    };
    return assignLefts(layered, [sources, targets], new Map(Object.entries(tops)), 100);
}

describe('assignLefts', () => {
    it('right-aligns every layer to its widest node', () => {
        const connections = [connect('c1', 's', 'out', 'narrow'), connect('c2', 's', 'out', 'wide')];
        const nodes = withPorts(
            [
                makeNode('s', NodeType.START),
                makeNode('narrow', NodeType.AGENT, { width: 200 }),
                makeNode('wide', NodeType.AGENT, { width: 400 }),
            ],
            connections
        );
        const layered = layeredComponent({ nodes, connections });
        const order = orderLayers(layered);

        const lefts = assignLefts(layered, order, assignTops(layered, order, 100), 100);

        expect(lefts.get('narrow')! + 200).toBe(lefts.get('wide')! + 400);
        expect(lefts.get('narrow')!).toBeGreaterThan(lefts.get('wide')!);
    });

    it.each([NodeType.TABLE, NodeType.CLASSIFICATION_TABLE] as const)(
        'adds no extra gap after a %s layer',
        (tableType) => {
            const connections = [
                connect('in', 's', 'out', 't', 'table-in'),
                connect('row', 't', tableRowRole(tableType, 0), 'child'),
                connect('next', 'child', 'out', 'last'),
            ];
            const nodes = withPorts(
                [
                    makeNode('s', NodeType.START),
                    tableNode('t', tableType, 1),
                    makeNode('child', NodeType.PYTHON, { height: 60 }),
                    makeNode('last', NodeType.PYTHON, { height: 60 }),
                ],
                connections
            );
            const layered = layeredComponent({ nodes, connections });
            const order = orderLayers(layered);

            const lefts = assignLefts(layered, order, assignTops(layered, order, 100), 100);

            // Every wire is straight, so no lane allowance: 100 after every layer, the table's too,
            // then up to the grid. Rights end on 10 (grid lefts + 330): 110.
            const afterTable = lefts.get('child')! - (lefts.get('t')! + 330);
            const afterPlain = lefts.get('last')! - (lefts.get('child')! + 330);
            expect(afterTable).toBe(110);
            expect(afterPlain).toBe(110);
        }
    );

    it('widens a gap by 20 per lane its bending wires need, up to 160', () => {
        const gapFor = (pairs: number): number => {
            const sources = Array.from({ length: pairs }, (_, index) => `s${index}`);
            const targets = Array.from({ length: pairs }, (_, index) => `t${index}`);
            // Each target 100 below its source: every wire bends, each in its own lane.
            const tops = Object.fromEntries([
                ...sources.map((id, index) => [id, index * 200]),
                ...targets.map((id, index) => [id, index * 200 + 100]),
            ]);
            const lefts = twoLayers(
                tops,
                sources,
                targets,
                sources.map((id, index) => wire(id, targets[index]))
            );
            return lefts.get('t0')! - (lefts.get('s0')! + 330);
        };
        const straightGap = (() => {
            const lefts = twoLayers({ a: 0, b: 0 }, ['a'], ['b'], [wire('a', 'b')]);
            return lefts.get('b')! - (lefts.get('a')! + 330);
        })();

        expect(straightGap).toBe(110); // 100, up to the grid (right edge 430 → left 540)
        expect(gapFor(1) - straightGap).toBe(20);
        expect(gapFor(3) - straightGap).toBe(60);
        expect(gapFor(8) - straightGap).toBe(160);
        expect(gapFor(12) - straightGap).toBe(160);
    });

    it('gives a fan-in to one port a single lane (a trunk), not one per wire', () => {
        const sources = ['a', 'b', 'c', 'd', 'e'];
        const tops = { ...Object.fromEntries(sources.map((id, index) => [id, index * 110])), m: 400 };
        const fanIn = twoLayers(
            tops,
            sources,
            ['m'],
            sources.map((id) => wire(id, 'm'))
        );
        const straight = twoLayers({ a: 0, m: 0 }, ['a'], ['m'], [wire('a', 'm')]);

        expect(fanIn.get('m')! - straight.get('m')!).toBe(20);
    });

    it('counts a back edge as one lane beside each end', () => {
        const layered: LayeredGraph = {
            nodes: new Map(['a', 'b', 'c'].map((id) => [id, box(id)])),
            edges: [wire('a', 'b'), wire('b', 'c')],
            layerOf: new Map([
                ['a', 0],
                ['b', 1],
                ['c', 2],
            ]),
            backEdges: [wire('c', 'b')],
            dummyOrigins: new Map(),
        };
        const tops = new Map([
            ['a', 0],
            ['b', 0],
            ['c', 0],
        ]);

        const lefts = assignLefts(layered, [['a'], ['b'], ['c']], tops, 100);

        // c → b loops back: a lane left of b (100 + 20, up to the grid: 130); c is the last layer.
        expect(lefts.get('b')! - (lefts.get('a')! + 330)).toBe(130);
        expect(lefts.get('c')! - (lefts.get('b')! + 330)).toBe(110);
    });
});
