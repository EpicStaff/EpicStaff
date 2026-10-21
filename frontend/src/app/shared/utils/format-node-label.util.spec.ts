import { formatNodeLabel, runtimeNodeNameToLabel } from './format-node-label.util';

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

describe('runtimeNodeNameToLabel', () => {
    it.each([
        { name: 'Fetch #3 #1742', label: 'Fetch #3' },
        { name: 'Fetch #1742', label: 'Fetch' },
        { name: 'Step #1 of #2 #99', label: 'Step #1 of #2' },
        { name: '', label: '' },
        { name: 'Session Failed', label: 'Session Failed' },
        { name: 'Fetch', label: 'Fetch' },
        { name: 'Fetch #', label: 'Fetch #' },
        { name: 'Fetch#12', label: 'Fetch#12' },
        { name: 'Fetch #12a', label: 'Fetch #12a' },
    ])('shows "$name" as "$label"', ({ name, label }) => {
        expect(runtimeNodeNameToLabel(name)).toBe(label);
    });

    // The backend runtime name is the label followed by " #<node id>" (graph_utils.runtime_node_name).
    it.each([
        { node: { node_name: 'Fetch', nodeNumber: 3 }, nodeId: 1742 },
        { node: { node_name: 'Fetch', nodeNumber: null }, nodeId: 1742 },
        { node: { node_name: 'Step #1', nodeNumber: 2 }, nodeId: 7 },
    ])(
        'gives back the label of $node.node_name numbered $node.nodeNumber from its runtime name',
        ({ node, nodeId }) => {
            const label = formatNodeLabel(node);

            expect(runtimeNodeNameToLabel(`${label} #${nodeId}`)).toBe(label);
        }
    );
});
