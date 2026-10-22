import { NodeType } from '@shared/models';

import { generateNodeDisplayName } from './generate-node-display-name.util';

describe('generateNodeDisplayName', () => {
    it('returns "__end_node__" for END type', () => {
        expect(generateNodeDisplayName(NodeType.END)).toBe('__end_node__');
    });

    it('returns "Start" for START type', () => {
        expect(generateNodeDisplayName(NodeType.START)).toBe('Start');
    });

    it.each([
        [NodeType.AGENT, 'Agent-Node'],
        [NodeType.TASK, 'Task-Node'],
        [NodeType.PYTHON, 'Python-Node'],
        [NodeType.TOOL, 'Tool-Node'],
        [NodeType.TABLE, 'Decision-Table'],
        [NodeType.NOTE, 'Note'],
        [NodeType.SUBGRAPH, 'Flow-Node'],
    ])('names a new %s node by its type prefix alone, without a number', (type, expectedName) => {
        expect(generateNodeDisplayName(type)).toBe(expectedName);
    });
});
