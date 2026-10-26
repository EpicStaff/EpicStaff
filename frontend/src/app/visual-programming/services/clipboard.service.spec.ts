import { TestBed } from '@angular/core/testing';
import { NodeType } from '@shared/models';

import { AgentNodeModel, NodeModel } from '../core/models/node.model';
import { ClipboardService } from './clipboard.service';
import { FlowService } from './flow.service';

function canvasNode(id: string, type: NodeType, overrides: Partial<NodeModel> = {}): NodeModel {
    return {
        id,
        backendId: 10,
        type,
        node_name: 'Node',
        data: {},
        position: { x: 0, y: 0 },
        ports: [],
        color: '',
        icon: '',
        input_map: {},
        output_variable_path: null,
        size: { width: 200, height: 100 },
        ...overrides,
    } as NodeModel;
}

describe('ClipboardService paste', () => {
    let flowService: FlowService;
    let clipboard: ClipboardService;

    beforeEach(() => {
        flowService = TestBed.inject(FlowService);
        clipboard = TestBed.inject(ClipboardService);
    });

    function copyAndPaste(...nodes: NodeModel[]): NodeModel[] {
        flowService.setFlow({ nodes, connections: [] });
        clipboard.copy({ fNodeIds: nodes.map((node) => node.id), fConnectionIds: [], fGroupIds: [] });
        return clipboard.paste({ x: 400, y: 400 }).newNodes;
    }

    it('keeps the copied name and gives the copy the next number', () => {
        const original = canvasNode('python-1', NodeType.PYTHON, { node_name: 'My custom', nodeNumber: 5 });
        flowService.setNodeNumberFloor(7);

        const [copy] = copyAndPaste(original);

        expect(copy.node_name).toBe('My custom');
        expect(copy.nodeNumber).toBe(8);
        expect(copy.backendId).toBeNull();
    });

    it('numbers several pasted nodes one after another', () => {
        const first = canvasNode('python-1', NodeType.PYTHON, { node_name: 'Fetch', nodeNumber: 1 });
        const second = canvasNode('task-1', NodeType.TASK, { node_name: 'Fetch', nodeNumber: 2 });

        const copies = copyAndPaste(first, second);

        expect(copies.map((copy) => [copy.node_name, copy.nodeNumber])).toEqual([
            ['Fetch', 3],
            ['Fetch', 4],
        ]);
    });

    it('gives a pasted note no number and does not use one up', () => {
        const note = canvasNode('note-1', NodeType.NOTE, { node_name: 'Remember this' });
        const python = canvasNode('python-1', NodeType.PYTHON, { node_name: 'Fetch', nodeNumber: 2 });

        const [noteCopy, pythonCopy] = copyAndPaste(note, python);

        expect(noteCopy.node_name).toBe('Remember this');
        expect(noteCopy.nodeNumber).toBeUndefined();
        expect(pythonCopy.nodeNumber).toBe(3);
    });

    it('numbers the copies in the order of the source numbers, not the selection order', () => {
        const ninth = canvasNode('python-9', NodeType.PYTHON, { node_name: 'Nine', nodeNumber: 9 });
        const fifth = canvasNode('task-5', NodeType.TASK, { node_name: 'Five', nodeNumber: 5 });
        const seventh = canvasNode('python-7', NodeType.PYTHON, { node_name: 'Seven', nodeNumber: 7 });
        flowService.setNodeNumberFloor(11);

        const copies = copyAndPaste(ninth, fifth, seventh);

        expect(copies.map((copy) => [copy.node_name, copy.nodeNumber])).toEqual([
            ['Nine', 14],
            ['Five', 12],
            ['Seven', 13],
        ]);
    });

    it('numbers a copied note-and-nodes selection without a note using up a number', () => {
        const seventh = canvasNode('python-7', NodeType.PYTHON, { node_name: 'Seven', nodeNumber: 7 });
        const note = canvasNode('note-1', NodeType.NOTE, { node_name: 'Remember this' });
        const fifth = canvasNode('task-5', NodeType.TASK, { node_name: 'Five', nodeNumber: 5 });
        flowService.setNodeNumberFloor(11);

        const copies = copyAndPaste(seventh, note, fifth);

        expect(copies.map((copy) => [copy.node_name, copy.nodeNumber])).toEqual([
            ['Seven', 13],
            ['Remember this', undefined],
            ['Five', 12],
        ]);
    });

    it('numbers a copy of a node that has no number last', () => {
        const legacy = canvasNode('python-1', NodeType.PYTHON, { node_name: 'Legacy' });
        const fifth = canvasNode('task-5', NodeType.TASK, { node_name: 'Five', nodeNumber: 5 });
        const seventh = canvasNode('python-7', NodeType.PYTHON, { node_name: 'Seven', nodeNumber: 7 });
        flowService.setNodeNumberFloor(11);

        const copies = copyAndPaste(legacy, fifth, seventh);

        expect(copies.map((copy) => [copy.node_name, copy.nodeNumber])).toEqual([
            ['Legacy', 14],
            ['Five', 12],
            ['Seven', 13],
        ]);
    });

    it("gives a copied agent's tasks no ids of the source's tasks, keeping their context by temp id", () => {
        const task = { name: 'Draft', instructions: '', output_schema: {} };
        const agent = canvasNode('agent-1', NodeType.AGENT, {
            data: {
                tasks: [
                    { ...task, id: 900, tempId: 'source-draft', contextRefs: [] },
                    { ...task, name: 'Review', id: 901, tempId: 'source-review', contextRefs: [{ id: 900 }] },
                    // Added since the last save: no id yet, and its context names the others by temp id.
                    {
                        ...task,
                        name: 'Publish',
                        tempId: 'source-publish',
                        contextRefs: [{ tempId: 'source-review' }],
                    },
                ],
            },
        } as Partial<NodeModel>);

        const [copy] = copyAndPaste(agent);

        const [draft, review, publish] = (copy as AgentNodeModel).data.tasks;
        expect([draft.id, review.id, publish.id]).toEqual([undefined, undefined, undefined]);
        expect([draft.tempId, review.tempId, publish.tempId]).not.toContain('source-draft');
        expect(review.contextRefs).toEqual([{ tempId: draft.tempId }]);
        expect(publish.contextRefs).toEqual([{ tempId: review.tempId }]);
    });
});
