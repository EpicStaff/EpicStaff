import { NodeType } from '@shared/models';

import { NodeModel } from '../models/node.model';
import { getNodeTitle } from './node-title.util';

const node = (fields: Record<string, unknown>): NodeModel => fields as unknown as NodeModel;

describe('getNodeTitle', () => {
    it.each([
        {
            case: 'a python node',
            given: node({ type: NodeType.PYTHON, node_name: 'Fetch', nodeNumber: 4 }),
            title: 'Fetch',
        },
        {
            case: 'an agent node whose name ends in a number',
            given: node({ type: NodeType.AGENT, node_name: 'Writer #2', nodeNumber: 7 }),
            title: 'Writer #2',
        },
        {
            case: 'a decision table',
            given: node({ type: NodeType.TABLE, node_name: 'Route', nodeNumber: 3, data: { name: 'Route' } }),
            title: 'Route',
        },
        {
            case: 'a decision table with no name yet',
            given: node({ type: NodeType.TABLE, node_name: '', nodeNumber: 3, data: {} }),
            title: '',
        },
        { case: 'a note', given: node({ type: NodeType.NOTE, node_name: 'Note', data: {} }), title: 'Note' },
    ])('shows the name of $case without its number', ({ given, title }) => {
        expect(getNodeTitle(given)).toBe(title);
    });
});
