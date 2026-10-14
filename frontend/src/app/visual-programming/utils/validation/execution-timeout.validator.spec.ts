import { NodeType } from '@shared/models';

import { NodeModel } from '../../core/models/node.model';
import { invalidExecutionTimeoutMessages } from './execution-timeout.validator';

function node(type: NodeType, executionTimeout: number | null | undefined, name = 'Node'): NodeModel {
    return { id: name, type, node_name: name, execution_timeout: executionTimeout } as unknown as NodeModel;
}

describe('invalidExecutionTimeoutMessages', () => {
    it.each([
        NodeType.PYTHON,
        NodeType.WEBHOOK_TRIGGER,
        NodeType.CLASSIFICATION_TABLE,
        NodeType.FILE_EXTRACTOR,
        NodeType.AUDIO_TO_TEXT,
    ])('refuses a %s node whose timeout was emptied', (type) => {
        expect(invalidExecutionTimeoutMessages([node(type, null, 'Run me')])).toEqual([
            '"Run me" needs an execution timeout of at least 1 whole minute',
        ]);
    });

    it('refuses a fractional, zero or negative timeout', () => {
        const nodes = [
            node(NodeType.PYTHON, 2.5, 'Fraction'),
            node(NodeType.PYTHON, 0, 'Zero'),
            node(NodeType.PYTHON, -3, 'Negative'),
        ];

        expect(invalidExecutionTimeoutMessages(nodes)).toEqual([
            '"Fraction" needs an execution timeout of at least 1 whole minute',
            '"Zero" needs an execution timeout of at least 1 whole minute',
            '"Negative" needs an execution timeout of at least 1 whole minute',
        ]);
    });

    it('lets a whole timeout of at least 1 minute through', () => {
        expect(invalidExecutionTimeoutMessages([node(NodeType.PYTHON, 1), node(NodeType.AUDIO_TO_TEXT, 60)])).toEqual(
            []
        );
    });

    it('lets a timeout above the ceiling through: the backend lowers it, so a lowered ceiling never blocks a save', () => {
        expect(invalidExecutionTimeoutMessages([node(NodeType.FILE_EXTRACTOR, 100_000)])).toEqual([]);
    });

    it('ignores nodes that run no sandbox code', () => {
        expect(
            invalidExecutionTimeoutMessages([node(NodeType.AGENT, undefined), node(NodeType.TABLE, undefined)])
        ).toEqual([]);
    });
});
