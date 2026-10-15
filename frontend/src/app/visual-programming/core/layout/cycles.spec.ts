import { NodeType } from '@shared/models';

import { ConnectionModel } from '../models/connection.model';
import { NodeModel } from '../models/node.model';
import { findBackEdges } from './cycles';
import { buildLayoutGraph } from './layout-graph';
import { connect, makeNode, tableNode, tableRowRole, withPorts } from './testing/fixtures';
import { shuffled } from './testing/random-graphs';

function backEdgesOf(nodes: NodeModel[], connections: ConnectionModel[]): string[] {
    const { graph, components } = buildLayoutGraph(withPorts(nodes, connections), connections);
    return [...findBackEdges(graph, components[0])].sort();
}

const python = (id: string): NodeModel => makeNode(id, NodeType.PYTHON);

describe('findBackEdges', () => {
    it('starts the DFS at a trigger, even when other ids sort first', () => {
        // From `a` the back edge would be b→a; from the trigger it is a→b.
        const connections = [
            connect('ab', 'a', 'out', 'b'),
            connect('ba', 'b', 'out', 'a'),
            connect('sb', 's', 'out', 'b'),
        ];

        expect(backEdgesOf([python('a'), python('b'), makeNode('s', NodeType.START)], connections)).toEqual(['ab']);
    });

    it('in a pure cycle, starts at the node with the highest (out − in)', () => {
        // out − in: a 0, b −1, c +1. From c: c→a→b, and b→c closes the cycle. From a (first id)
        // the back edges would be c→a and c→b.
        const connections = [
            connect('ab', 'a', 'out', 'b'),
            connect('bc', 'b', 'out', 'c'),
            connect('ca', 'c', 'out', 'a'),
            connect('cb', 'c', 'out2', 'b'),
        ];

        expect(backEdgesOf([python('a'), python('b'), python('c')], connections)).toEqual(['bc']);
    });

    it('visits a table in row order, not connection order', () => {
        // p0 and p1 loop into each other. Row 0 first: t → p0 → p1, so p1 → p0 is the back edge;
        // row 1 first (the array order here) would make it p0 → p1.
        const connections = [
            connect('in', 's', 'out', 't', 'table-in'),
            connect('row1', 't', tableRowRole(NodeType.TABLE, 1), 'p1'),
            connect('row0', 't', tableRowRole(NodeType.TABLE, 0), 'p0'),
            connect('p0p1', 'p0', 'out', 'p1'),
            connect('p1p0', 'p1', 'out', 'p0'),
        ];
        const nodes = [makeNode('s', NodeType.START), tableNode('t', NodeType.TABLE, 2), python('p0'), python('p1')];

        expect(backEdgesOf(nodes, connections)).toEqual(['p1p0']);
    });

    it('counts an edge into a trigger as a back edge', () => {
        const connections = [connect('sa', 's', 'out', 'a'), connect('xs', 'x', 'out', 's')];

        expect(backEdgesOf([makeNode('s', NodeType.START), python('a'), python('x')], connections)).toEqual(['xs']);
    });

    it('gives the same back edges whatever the input order', () => {
        const nodes = [python('a'), python('b'), python('c'), python('d')];
        const connections = [
            connect('ab', 'a', 'out', 'b'),
            connect('bc', 'b', 'out', 'c'),
            connect('cd', 'c', 'out', 'd'),
            connect('da', 'd', 'out', 'a'),
            connect('ca', 'c', 'out', 'a'),
        ];
        const expected = backEdgesOf(nodes, connections);

        for (const seed of [1, 2, 3]) {
            expect(backEdgesOf(shuffled(nodes, seed), shuffled(connections, seed + 10))).toEqual(expected);
        }
    });
});
