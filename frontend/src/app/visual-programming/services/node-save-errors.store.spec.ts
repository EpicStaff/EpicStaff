import { TestBed } from '@angular/core/testing';
import { NodeType } from '@shared/models';

import { NodeModel } from '../core/models/node.model';
import { SaveFieldError } from '../utils/save/bulk-save-errors';
import { NodeSaveErrorsStore } from './node-save-errors.store';

const instructionsOfTask: SaveFieldError = {
    field: 'instructions',
    sentValue: 'Use {context._x}',
    messages: ['Refused.'],
};
const inputMap: SaveFieldError = { field: 'input_map', sentValue: { a: 'variables._x' }, messages: ['Bad path.'] };
const taskRow = (field: string): SaveFieldError => ({
    field,
    child: { list: 'tasks', key: 't-1', position: 0 },
    sentValue: 'Say {topic!r}',
    messages: [`${field} refused.`],
});
const promptRow = (field: string): SaveFieldError => ({
    field,
    child: { list: 'prompt_configs', key: 'classify', position: 0 },
    sentValue: 'Pull {context._x}',
    messages: [`${field} refused.`],
});

function node(type: NodeType): NodeModel {
    return { id: 'node-1', type } as NodeModel;
}

describe('NodeSaveErrorsStore', () => {
    let store: NodeSaveErrorsStore;

    beforeEach(() => {
        store = TestBed.inject(NodeSaveErrorsStore);
    });

    describe('the messages of one field', () => {
        beforeEach(() => store.setAll(new Map([['node-1', [instructionsOfTask, taskRow('instructions')]]])));

        it('are shown while the field holds what was sent, hidden once edited, and back if the edit is undone', () => {
            expect(store.fieldMessages('node-1', 'instructions', 'Use {context._x}')).toEqual(['Refused.']);
            expect(store.fieldMessages('node-1', 'instructions', 'Use {topic}')).toEqual([]);
            expect(store.fieldMessages('node-1', 'instructions', 'Use {context._x}')).toEqual(['Refused.']);
        });

        it('of a child row are told apart from the node field of the same name, and from other rows', () => {
            const row = { list: 'tasks', key: 't-1' };

            expect(store.fieldMessages('node-1', 'instructions', 'Say {topic!r}', row)).toEqual([
                'instructions refused.',
            ]);
            expect(store.fieldMessages('node-1', 'instructions', 'Say {topic!r}')).toEqual([]);
            expect(store.fieldMessages('node-1', 'instructions', 'Say {topic!r}', { ...row, key: 't-2' })).toEqual([]);
        });
    });

    it.each([
        [NodeType.TASK, [instructionsOfTask, inputMap], [inputMap]],
        [NodeType.KNOWLEDGE_RETRIEVER, [{ ...instructionsOfTask, field: 'query' }, inputMap], [inputMap]],
        [NodeType.AGENT, [taskRow('instructions'), taskRow('name'), inputMap], [taskRow('name'), inputMap]],
        [
            NodeType.CLASSIFICATION_TABLE,
            [promptRow('prompt_text'), promptRow('input_map'), inputMap],
            [promptRow('prompt_text'), promptRow('input_map'), inputMap],
        ],
        [NodeType.PYTHON, [instructionsOfTask, inputMap], [instructionsOfTask, inputMap]],
    ])('leaves out of the node-level list of a %s node only the field its panel shows', (type, errors, nodeLevel) => {
        store.setAll(new Map([['node-1', errors]]));

        expect(store.nodeLevelErrors(node(type))).toEqual(nodeLevel);
    });

    it("replaces one node's errors on a one-node save, keeping the other nodes'", () => {
        store.setAll(
            new Map([
                ['node-1', [inputMap]],
                ['node-2', [inputMap]],
            ])
        );

        store.setForNode('node-1', []);

        expect([...store.errors().keys()]).toEqual(['node-2']);
    });
});
