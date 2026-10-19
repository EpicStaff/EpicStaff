import { formatNodeLabel } from './format-node-label.util';

describe('formatNodeLabel', () => {
    it.each([
        { node: { node_name: 'Approver', nodeNumber: 3 }, label: 'Approver #3' },
        { node: { node_name: 'Approver', nodeNumber: 0 }, label: 'Approver #0' },
        { node: { node_name: 'Approver', nodeNumber: undefined }, label: 'Approver' },
        { node: { node_name: 'Approver', nodeNumber: null }, label: 'Approver' },
        { node: { node_name: 'Start', nodeNumber: undefined }, label: 'Start' },
    ])('labels $node.node_name numbered $node.nodeNumber as "$label"', ({ node, label }) => {
        expect(formatNodeLabel(node)).toBe(label);
    });
});
