import { NodeType } from '@shared/models';

import { connect, layeredComponent, makeNode, withPorts } from './testing/fixtures';

describe('splitLongEdges', () => {
    it('turns an edge spanning 3 layers into a chain through 2 dummies at offset 0', () => {
        const nodes = [makeNode('s', NodeType.START), ...['a', 'b', 'c'].map((id) => makeNode(id, NodeType.PYTHON))];
        const connections = [
            connect('sa', 's', 'out', 'a'),
            connect('ab', 'a', 'out', 'b'),
            connect('bc', 'b', 'out', 'c'),
            connect('long', 's', 'out2', 'c'),
        ];

        const layered = layeredComponent({ nodes: withPorts(nodes, connections), connections });

        expect(layered.layerOf.get('~d:long:1')).toBe(1);
        expect(layered.layerOf.get('~d:long:2')).toBe(2);
        expect(layered.nodes.get('~d:long:1')).toMatchObject({ width: 0, height: 0, isDummy: true });
        const chain = layered.edges.filter((edge) => edge.id.startsWith('~e:long:'));
        expect(
            chain.map(({ source, target, sourceOffsetY, targetOffsetY }) => [
                source,
                target,
                sourceOffsetY,
                targetOffsetY,
            ])
        ).toEqual([
            ['s', '~d:long:1', 50, 0],
            ['~d:long:1', '~d:long:2', 0, 0],
            ['~d:long:2', 'c', 0, 50],
        ]);
        expect(layered.dummyOrigins.get('~d:long:2')!.id).toBe('long');
        for (const edge of layered.edges) {
            expect(layered.layerOf.get(edge.target)! - layered.layerOf.get(edge.source)!).toBe(1);
        }
    });

    it('keeps back edges whole, in their original direction, with no dummies', () => {
        const nodes = [makeNode('s', NodeType.START), ...['a', 'b', 'c'].map((id) => makeNode(id, NodeType.PYTHON))];
        const connections = [
            connect('sa', 's', 'out', 'a'),
            connect('ab', 'a', 'out', 'b'),
            connect('bc', 'b', 'out', 'c'),
            connect('loop', 'c', 'out', 'a'),
        ];

        const layered = layeredComponent({ nodes: withPorts(nodes, connections), connections });

        expect(layered.backEdges.map((edge) => [edge.id, edge.source, edge.target])).toEqual([['loop', 'c', 'a']]);
        expect([...layered.nodes.values()].some((node) => node.isDummy)).toBe(false);
    });
});
