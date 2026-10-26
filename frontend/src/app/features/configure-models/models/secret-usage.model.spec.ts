import { NodeType, SecretUsageNodeDto, SecretUsageResponse } from '@shared/models';

import { SecretUsageFlowCategory, toSecretUsageSummary } from './secret-usage.model';

function flowsUsing(nodes: SecretUsageNodeDto[]): SecretUsageResponse {
    return {
        readable_total: 1,
        hidden_total: 0,
        categories: [{ key: 'flows', items: [{ id: 7, name: 'Billing', nodes }] }],
    };
}

function shownNodes(response: SecretUsageResponse): { id: number; name: string }[] {
    const flows = toSecretUsageSummary(response).categories[0] as SecretUsageFlowCategory;
    return flows.items[0].nodes.map(({ id, name }) => ({ id, name }));
}

describe('toSecretUsageSummary flow nodes', () => {
    it('keeps two same-named nodes of one type as two rows, told apart by their numbers', () => {
        const response = flowsUsing([
            { id: 11, node_number: 1, name: 'Fetch', node_type: NodeType.PYTHON, code_field: null },
            { id: 12, node_number: 2, name: 'Fetch', node_type: NodeType.PYTHON, code_field: null },
        ]);

        expect(shownNodes(response)).toEqual([
            { id: 11, name: 'Fetch #1' },
            { id: 12, name: 'Fetch #2' },
        ]);
    });

    it('shows a node using the secret in both its pre and post code once', () => {
        const response = flowsUsing([
            { id: 21, node_number: 3, name: 'Route', node_type: NodeType.CLASSIFICATION_TABLE, code_field: 'pre' },
            { id: 21, node_number: 3, name: 'Route', node_type: NodeType.CLASSIFICATION_TABLE, code_field: 'post' },
        ]);

        expect(shownNodes(response)).toEqual([{ id: 21, name: 'Route #3' }]);
    });

    it('labels an unnumbered node by its name alone', () => {
        const response = flowsUsing([
            { id: 31, node_number: null, name: 'Hook', node_type: NodeType.WEBHOOK_TRIGGER, code_field: null },
        ]);

        expect(shownNodes(response)).toEqual([{ id: 31, name: 'Hook' }]);
    });
});
