import { NodeType } from '@shared/models';

import { NodeModel } from '../../core/models/node.model';
import { invalidExecutionTimeoutMessages } from './execution-timeout.validator';

const MIN_SECONDS = 5;

function pythonNode(name: string, executionTimeout: number | undefined): NodeModel {
    return {
        id: name,
        type: NodeType.PYTHON,
        node_name: name,
        data: { execution_timeout: executionTimeout },
    } as unknown as NodeModel;
}

function webhookNode(name: string, executionTimeout: number | undefined): NodeModel {
    return {
        id: name,
        type: NodeType.WEBHOOK_TRIGGER,
        node_name: name,
        data: { python_code: { execution_timeout: executionTimeout } },
    } as unknown as NodeModel;
}

function tableNode(
    name: string,
    preTimeout: number | undefined,
    postTimeout: number | undefined,
    { preCode = 'def main(): pass', postCode = 'def main(): pass', preSecretIds = [] as number[] } = {}
): NodeModel {
    return {
        id: name,
        type: NodeType.CLASSIFICATION_TABLE,
        node_name: name,
        data: {
            table: {
                pre_computation: { code: preCode, secret_ids: preSecretIds, execution_timeout: preTimeout },
                post_computation: { code: postCode, execution_timeout: postTimeout },
            },
        },
    } as unknown as NodeModel;
}

describe('invalidExecutionTimeoutMessages', () => {
    const message = (name: string): string => `"${name}" needs an execution timeout of at least 5 seconds`;

    it('names each node with an invalid timeout on one of its codes', () => {
        const nodes = [
            pythonNode('Python', 2),
            webhookNode('Webhook', 1.5),
            tableNode('Pre', 0, 60),
            tableNode('Post', 60, 3),
        ];

        expect(invalidExecutionTimeoutMessages(nodes, MIN_SECONDS)).toEqual([
            message('Python'),
            message('Webhook'),
            message('Pre'),
            message('Post'),
        ]);
    });

    it('names a table once even when both its codes are invalid', () => {
        expect(invalidExecutionTimeoutMessages([tableNode('Both', 1, 2)], MIN_SECONDS)).toEqual([message('Both')]);
    });

    it('lets a valid timeout through, however long: the backend lowers one above its maximum', () => {
        const nodes = [
            pythonNode('Python', MIN_SECONDS),
            webhookNode('Webhook', 1_000_000),
            tableNode('Table', 60, 90),
        ];

        expect(invalidExecutionTimeoutMessages(nodes, MIN_SECONDS)).toEqual([]);
    });

    it('lets an absent timeout through: the backend applies its default', () => {
        const nodes = [
            pythonNode('Python', undefined),
            webhookNode('Webhook', undefined),
            tableNode('Table', undefined, undefined),
        ];

        expect(invalidExecutionTimeoutMessages(nodes, MIN_SECONDS)).toEqual([]);
    });

    it('lets through a table without a pre- or post-computation', () => {
        const table = {
            id: 'Table',
            type: NodeType.CLASSIFICATION_TABLE,
            node_name: 'Table',
            data: { table: {} },
        } as unknown as NodeModel;

        expect(invalidExecutionTimeoutMessages([table], MIN_SECONDS)).toEqual([]);
    });

    it('lets through the timeout of a pre- or post-computation without code: the save drops it', () => {
        const nodes = [
            tableNode('Empty pre', 1, 60, { preCode: '  ' }),
            tableNode('Empty post', 60, 2, { postCode: '' }),
        ];

        expect(invalidExecutionTimeoutMessages(nodes, MIN_SECONDS)).toEqual([]);
    });

    it('checks the timeout of a computation without code but with secrets: the save keeps it', () => {
        const table = tableNode('Secrets only', 1, 60, { preCode: '', preSecretIds: [3] });

        expect(invalidExecutionTimeoutMessages([table], MIN_SECONDS)).toEqual([message('Secrets only')]);
    });

    it('ignores nodes that run no python code', () => {
        const agent = { id: 'Agent', type: NodeType.AGENT, node_name: 'Agent', data: {} } as unknown as NodeModel;

        expect(invalidExecutionTimeoutMessages([agent], MIN_SECONDS)).toEqual([]);
    });
});
