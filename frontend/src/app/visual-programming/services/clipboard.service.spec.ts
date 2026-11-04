import { TestBed } from '@angular/core/testing';
import { ActionCode, NodeType, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../services/auth/permissions.service';
import { ConnectionModel } from '../core/models/connection.model';
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

    describe('decision table next-node refs', () => {
        function tableNode(id: string, type: NodeType.TABLE | NodeType.CLASSIFICATION_TABLE): NodeModel {
            return canvasNode(id, type, {
                data: {
                    table: {
                        default_next_node: 'original-default',
                        next_error_node: 'original-error',
                        condition_groups: [
                            { group_name: 'Billing', route_code: 'billing', next_node: 'original-billing' },
                            { group_name: 'Support', route_code: 'support', next_node: 'original-support' },
                        ],
                    },
                },
            } as Partial<NodeModel>);
        }

        function tableOf(node: NodeModel): {
            default_next_node: string | null;
            next_error_node: string | null;
            condition_groups: { next_node: string | null }[];
        } {
            return (node.data as { table: ReturnType<typeof tableOf> }).table;
        }

        it.each([NodeType.TABLE, NodeType.CLASSIFICATION_TABLE] as const)(
            'drops the original targets from a %s pasted without them',
            (type) => {
                const [copy] = copyAndPaste(tableNode('table-1', type));

                const table = tableOf(copy);
                expect(table.default_next_node).toBeNull();
                expect(table.next_error_node).toBeNull();
                expect(table.condition_groups.map((group) => group.next_node)).toEqual([null, null]);
            }
        );

        it('points a pasted classification table at the pasted copy of its route target', () => {
            const cdt = tableNode('cdt-1', NodeType.CLASSIFICATION_TABLE);
            const target = canvasNode('python-1', NodeType.PYTHON, { node_name: 'Billing handler' });
            const connection: ConnectionModel = {
                id: 'cdt-1_decision-route-billing+python-1_python-in',
                category: 'default',
                behavior: 'fixed',
                type: 'bezier',
                data: null,
                sourceNodeId: 'cdt-1',
                targetNodeId: 'python-1',
                sourcePortId: 'cdt-1_decision-route-billing',
                targetPortId: 'python-1_python-in',
            };
            flowService.setFlow({ nodes: [cdt, target], connections: [connection] });
            clipboard.copy({ fNodeIds: ['cdt-1', 'python-1'], fConnectionIds: [], fGroupIds: [] });

            const { newNodes, newConnections } = clipboard.paste({ x: 400, y: 400 });

            const [cdtCopy, targetCopy] = newNodes;
            expect(targetCopy.id).not.toBe('python-1');
            expect(tableOf(cdtCopy).condition_groups.map((group) => group.next_node)).toEqual([targetCopy.id, null]);
            expect(tableOf(cdtCopy).default_next_node).toBeNull();
            expect(newConnections).toEqual([
                expect.objectContaining({
                    sourcePortId: `${cdtCopy.id}_decision-route-billing`,
                    targetPortId: `${targetCopy.id}_python-in`,
                }),
            ]);
        });
    });
});

describe('ClipboardService paste storage grants', () => {
    function pasteAs(files: ActionCode[], ...nodes: NodeModel[]): NodeModel[] {
        TestBed.configureTestingModule({
            providers: [
                {
                    provide: PermissionsService,
                    useValue: {
                        can: (resource: ResourceCode, action: ActionCode) =>
                            resource === ResourceCode.Files ? files.includes(action) : true,
                    },
                },
            ],
        });
        const flowService = TestBed.inject(FlowService);
        const clipboard = TestBed.inject(ClipboardService);
        flowService.setFlow({ nodes, connections: [] });
        clipboard.copy({ fNodeIds: nodes.map((node) => node.id), fConnectionIds: [], fGroupIds: [] });
        return clipboard.paste({ x: 400, y: 400 }).newNodes;
    }

    it('turns off the flags of a copy that the user lacks the permissions for', () => {
        const python = canvasNode('python-1', NodeType.PYTHON, {
            storageGrants: { read: true, write: true, delete: true },
        });

        const [copy] = pasteAs([ActionCode.Read, ActionCode.Delete], python);

        expect(copy.storageGrants).toEqual({ read: true, write: false, delete: true });
    });

    it('makes a not-configured copy explicit, with what the user holds, unless they hold all three', () => {
        const stored = { read: null, write: null, delete: null };
        const python = canvasNode('python-1', NodeType.PYTHON, { storageGrants: stored });

        const [limited] = pasteAs([ActionCode.Read], python);

        expect(limited.storageGrants).toEqual({ read: true, write: false, delete: false });
    });

    it('keeps a not-configured copy not configured for a user who holds all three', () => {
        const stored = { read: null, write: null, delete: null };
        const python = canvasNode('python-1', NodeType.PYTHON, { storageGrants: stored });

        const [copy] = pasteAs([ActionCode.Read, ActionCode.Create, ActionCode.Update, ActionCode.Delete], python);

        expect(copy.storageGrants).toEqual(stored);
    });

    it('caps each slot of a classification table copy', () => {
        const table = canvasNode('cdt-1', NodeType.CLASSIFICATION_TABLE, {
            preStorageGrants: { read: true, write: false, delete: true },
            postStorageGrants: { read: false, write: true, delete: false },
        } as Partial<NodeModel>);

        const [copy] = pasteAs([ActionCode.Read], table);

        expect(copy).toMatchObject({
            preStorageGrants: { read: true, write: false, delete: false },
            postStorageGrants: { read: false, write: false, delete: false },
        });
    });
});
