import { TestBed } from '@angular/core/testing';
import { ICurrentSelection } from '@foblex/flow';
import { NodeType } from '@shared/models';

import { NodeModel } from '../core/models/node.model';
import { mapPythonNodeToModel } from '../utils/load/nodes/python-node.mapper';
import { LIVE_NODE_UUID, livePython } from '../utils/testing/live-graph.fixture';
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
});

describe('ClipboardService node uuid', () => {
    let clipboard: ClipboardService;
    const sourceNode = mapPythonNodeToModel(livePython);

    beforeEach(() => {
        TestBed.inject(FlowService).setFlow({ nodes: [sourceNode], connections: [] });
        clipboard = TestBed.inject(ClipboardService);
        const selection: ICurrentSelection = { fNodeIds: [sourceNode.id], fGroupIds: [], fConnectionIds: [] };
        clipboard.copy(selection);
    });

    it('gives a pasted node a new uuid, different from its source', () => {
        expect(sourceNode.nodeUuid).toBe(LIVE_NODE_UUID.python);

        const [pasted] = clipboard.paste({ x: 100, y: 100 }).newNodes;

        expect(pasted.backendId).toBeNull();
        expect(pasted.nodeUuid).toEqual(expect.any(String));
        expect(pasted.nodeUuid).not.toBe(sourceNode.nodeUuid);
    });

    it('gives each paste of the same copy its own uuid', () => {
        const [first] = clipboard.paste({ x: 100, y: 100 }).newNodes;
        const [second] = clipboard.paste({ x: 300, y: 100 }).newNodes;

        expect(first.nodeUuid).not.toBe(second.nodeUuid);
    });
});
