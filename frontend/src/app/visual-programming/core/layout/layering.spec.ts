import { NodeType } from '@shared/models';

import { ConnectionModel } from '../models/connection.model';
import { NodeModel } from '../models/node.model';
import { findBackEdges } from './cycles';
import { assignLayers } from './layering';
import { buildLayoutGraph } from './layout-graph';
import { connect, makeNode, withPorts } from './testing/fixtures';

function layersOf(nodes: NodeModel[], connections: ConnectionModel[]): Record<string, number> {
    const { graph, components } = buildLayoutGraph(withPorts(nodes, connections), connections);
    const layers = assignLayers(graph, components[0], findBackEdges(graph, components[0]));
    return Object.fromEntries([...layers].sort(([a], [b]) => (a < b ? -1 : 1)));
}

const python = (id: string): NodeModel => makeNode(id, NodeType.PYTHON);

describe('assignLayers', () => {
    it('puts a merge node one layer right of its deepest parent', () => {
        const nodes = [makeNode('root', NodeType.START), ...['a', 'b1', 'b2', 'merge', 'after'].map(python)];
        const connections = [
            connect('c1', 'root', 'out1', 'a'),
            connect('c2', 'a', 'out', 'merge'),
            connect('c3', 'root', 'out2', 'b1'),
            connect('c4', 'b1', 'out', 'b2'),
            connect('c5', 'b2', 'out', 'merge'),
            connect('c6', 'b2', 'out2', 'after'),
        ];

        const { a, b2, merge, after } = layersOf(nodes, connections);

        expect(merge).toBe(b2 + 1);
        expect(after).toBe(merge);
        // Tightening: a's only successor is two layers away, so a moves next to it.
        expect(a).toBe(b2);
    });

    it('keeps a trigger on layer 0 while tightening pulls a plain source with only far successors', () => {
        const nodes = [makeNode('start', NodeType.START), ...['source', 'a', 'b', 'c', 'late'].map(python)];
        const connections = [
            connect('c1', 'source', 'out', 'a'),
            connect('c2', 'a', 'out', 'b'),
            connect('c3', 'b', 'out', 'c'),
            connect('c4', 'start', 'out', 'c'),
            connect('c5', 'late', 'out', 'c'),
        ];

        expect(layersOf(nodes, connections)).toEqual({ a: 1, b: 2, c: 3, late: 2, source: 0, start: 0 });
    });

    it('lays a cycle out left to right from its entry, the loop edge reversed', () => {
        const nodes = [makeNode('start', NodeType.START), ...['x', 'y', 'z'].map(python)];
        const connections = [
            connect('c1', 'start', 'out', 'x'),
            connect('c2', 'x', 'out', 'y'),
            connect('c3', 'y', 'back', 'x'),
            connect('c4', 'y', 'out', 'z'),
        ];

        expect(layersOf(nodes, connections)).toEqual({ start: 0, x: 1, y: 2, z: 3 });
    });
});
