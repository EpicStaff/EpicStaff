import { NodeType } from '@shared/models';

import { generateMultipleNodeDisplayNames, generateNodeDisplayName } from './generate-node-display-name.util';

describe('generateNodeDisplayName', () => {
    it('returns "__end_node__" for END type regardless of nodeNumber', () => {
        expect(generateNodeDisplayName(NodeType.END)).toBe('__end_node__');
        expect(generateNodeDisplayName(NodeType.END, 3)).toBe('__end_node__');
    });

    it('returns "Start" for START type regardless of nodeNumber', () => {
        expect(generateNodeDisplayName(NodeType.START)).toBe('Start');
        expect(generateNodeDisplayName(NodeType.START, 1)).toBe('Start');
    });

    it('returns prefix with badge number when nodeNumber is provided', () => {
        expect(generateNodeDisplayName(NodeType.AGENT, 1)).toBe('Agent-Node #1');
        expect(generateNodeDisplayName(NodeType.TASK, 42)).toBe('Task-Node #42');
    });

    it('returns just the prefix when nodeNumber is undefined', () => {
        expect(generateNodeDisplayName(NodeType.AGENT)).toBe('Agent-Node');
    });

    it.each([
        [NodeType.PYTHON, 'Python-Node'],
        [NodeType.TOOL, 'Tool-Node'],
        [NodeType.TABLE, 'Decision-Table'],
        [NodeType.NOTE, 'Note'],
        [NodeType.SUBGRAPH, 'Flow-Node'],
    ])('uses the correct prefix for %s', (type, expectedPrefix) => {
        expect(generateNodeDisplayName(type, 1)).toBe(`${expectedPrefix} #1`);
    });
});

describe('generateMultipleNodeDisplayNames', () => {
    it('generates names for multiple nodes in order', () => {
        const nodes = [{ type: NodeType.AGENT }, { type: NodeType.TASK }, { type: NodeType.PYTHON }];
        const numbers = [1, 2, 3];

        const names = generateMultipleNodeDisplayNames(nodes, numbers);

        expect(names).toEqual(['Agent-Node #1', 'Task-Node #2', 'Python-Node #3']);
    });

    it('returns an empty array for empty input', () => {
        expect(generateMultipleNodeDisplayNames([], [])).toEqual([]);
    });
});
