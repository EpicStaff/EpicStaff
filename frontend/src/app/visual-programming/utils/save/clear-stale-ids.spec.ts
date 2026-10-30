import { NodeType } from '@shared/models';

import { GraphDto } from '../../../features/flows/models/graph.model';
import { AgentNode, AgentNodeTaskUi } from '../../core/models/agent-node.model';
import { ConnectionModel } from '../../core/models/connection.model';
import { FlowModel } from '../../core/models/flow.model';
import { AgentNodeModel, NodeModel } from '../../core/models/node.model';
import { mapAgentNodeToModel } from '../load/nodes/agent-node.mapper';
import { clearStaleIds } from './clear-stale-ids';
import { buildUuidToBackendIdMap, getConnectionDiff, getNodeDiff } from './diff';
import { patchFlowStateWithBackendIds } from './patch';
import { buildBulkSavePayload } from './payload';

function node(id: string, backendId: number | null): NodeModel {
    return { id, backendId } as unknown as NodeModel;
}

function connection(id: string, edgeBackendId: number | null): ConnectionModel {
    return {
        id,
        sourceNodeId: 'a',
        targetNodeId: 'b',
        data: edgeBackendId == null ? null : { id: edgeBackendId },
    } as unknown as ConnectionModel;
}

function task(tempId: string, id?: number, contextRefs: AgentNodeTaskUi['contextRefs'] = []): AgentNodeTaskUi {
    return { id, tempId, name: tempId, instructions: '', output_schema: {}, contextRefs };
}

function agentNode(id: string, backendId: number | null, tasks: AgentNodeTaskUi[]): AgentNodeModel {
    return { id, backendId, type: NodeType.AGENT, data: { tasks } } as unknown as AgentNodeModel;
}

function tasksOf(flow: FlowModel, nodeId: string): AgentNodeTaskUi[] {
    return (flow.nodes.find((n) => n.id === nodeId) as AgentNodeModel).data.tasks;
}

describe('clearStaleIds', () => {
    it('clears backendId on a node whose backendId is not in the baseline (resurrected by undo)', () => {
        const previous: FlowModel = { nodes: [node('keep-uuid', 5)], connections: [] };
        const current: FlowModel = {
            nodes: [node('keep-uuid', 5), node('resurrected-uuid', 3)],
            connections: [],
        };

        const result = clearStaleIds(previous, current);

        const persisted = result.nodes.find((n) => n.id === 'keep-uuid');
        const orphaned = result.nodes.find((n) => n.id === 'resurrected-uuid');
        expect(persisted!.backendId).toBe(5); // untouched
        expect(orphaned!.backendId).toBeNull(); // cleared -> treated as new (temp_id)
    });

    it('clears data on a connection whose edge id is not in the baseline', () => {
        const previous: FlowModel = { nodes: [], connections: [connection('c-keep', 10)] };
        const current: FlowModel = {
            nodes: [],
            connections: [connection('c-keep', 10), connection('c-orphan', 7)],
        };

        const result = clearStaleIds(previous, current);

        expect(result.connections.find((c) => c.id === 'c-keep')!.data?.id).toBe(10);
        expect(result.connections.find((c) => c.id === 'c-orphan')!.data).toBeNull();
    });

    it('is a no-op when there are no stale ids', () => {
        const previous: FlowModel = {
            nodes: [node('x', 1)],
            connections: [connection('c', 2)],
        };
        const current: FlowModel = {
            nodes: [node('x', 1), node('new', null)],
            connections: [connection('c', 2)],
        };

        const result = clearStaleIds(previous, current);

        expect(result.nodes.find((n) => n.id === 'x')!.backendId).toBe(1);
        expect(result.nodes.find((n) => n.id === 'new')!.backendId).toBeNull();
        expect(result.connections[0].data?.id).toBe(2);
    });

    describe('agent tasks', () => {
        it('drops the id of a task restored by undo and points sibling context links at its tempId', () => {
            const previous: FlowModel = {
                nodes: [agentNode('n', 1, [task('t-a', 12)])],
                connections: [],
            };
            const current: FlowModel = {
                nodes: [
                    agentNode('n', 1, [
                        task('t-a', 12),
                        task('t-b', 13),
                        task('t-c', undefined, [{ id: 13 }, { id: 12 }]),
                    ]),
                ],
                connections: [],
            };

            const tasks = tasksOf(clearStaleIds(previous, current), 'n');

            expect(tasks[0].id).toBe(12);
            expect(tasks[1].id).toBeUndefined();
            expect(tasks[1].tempId).toBe('t-b');
            expect(tasks[2].contextRefs).toEqual([{ tempId: 't-b' }, { id: 12 }]);
        });

        it('drops every task id and rewrites links when the whole agent node was restored with a stale backendId', () => {
            const previous: FlowModel = { nodes: [], connections: [] };
            const current: FlowModel = {
                nodes: [agentNode('n', 4, [task('t-a', 20), task('t-b', 21, [{ id: 20 }])])],
                connections: [],
            };

            const result = clearStaleIds(previous, current);
            const tasks = tasksOf(result, 'n');

            expect(result.nodes[0].backendId).toBeNull();
            expect(tasks.map((t) => t.id)).toEqual([undefined, undefined]);
            expect(tasks[1].contextRefs).toEqual([{ tempId: 't-a' }]);
        });

        it('treats an agent node without a backendId as having no saved tasks', () => {
            const previous: FlowModel = { nodes: [agentNode('other', 1, [task('t-x', 30)])], connections: [] };
            const current: FlowModel = { nodes: [agentNode('n', null, [task('t-a', 30)])], connections: [] };

            expect(tasksOf(clearStaleIds(previous, current), 'n')[0].id).toBeUndefined();
        });

        it('leaves nodes and tasks unchanged when every task id is saved', () => {
            const previous: FlowModel = {
                nodes: [agentNode('n', 1, [task('t-a', 12), task('t-b', 13, [{ id: 12 }])])],
                connections: [],
            };
            const current: FlowModel = {
                nodes: [agentNode('n', 1, [task('t-a', 12), task('t-b', 13, [{ id: 12 }]), task('t-new')])],
                connections: [],
            };

            const result = clearStaleIds(previous, current);

            expect(result.nodes[0]).toBe(current.nodes[0]);
            expect(tasksOf(result, 'n').map((t) => t.id)).toEqual([12, 13, undefined]);
        });

        it('treats a task with undefined contextRefs as having no links', () => {
            const previous: FlowModel = { nodes: [agentNode('n', 1, [task('t-a', 12)])], connections: [] };
            const staleTask = { ...task('t-b', 13), contextRefs: undefined } as unknown as AgentNodeTaskUi;
            const current: FlowModel = { nodes: [agentNode('n', 1, [task('t-a', 12), staleTask])], connections: [] };

            const tasks = tasksOf(clearStaleIds(previous, current), 'n');

            expect(tasks[1].id).toBeUndefined();
            expect(tasks[1].contextRefs).toEqual([]);
        });

        it('rewrites a sibling link inside a node restored with a stale backendId', () => {
            const previous: FlowModel = { nodes: [], connections: [] };
            const current: FlowModel = {
                nodes: [agentNode('n', 4, [task('t-a', 20, [{ id: 21 }]), task('t-b', 21)])],
                connections: [],
            };

            const tasks = tasksOf(clearStaleIds(previous, current), 'n');

            expect(tasks[0].contextRefs).toEqual([{ tempId: 't-b' }]);
            expect(tasks[1].id).toBeUndefined();
        });
    });

    describe('save round trip after undo restored a deleted task', () => {
        const savedAgent: AgentNode = {
            created_at: '2026-01-01T00:00:00Z',
            created_by: null,
            last_edited_by: null,
            last_edited_at: null,
            id: 50,
            metadata: {},
            node_number: 1,
            node_name: 'Agent #1',
            input_map: {},
            output_variable_path: null,
            agent_definition: 3,
            surface_list: [],
            inline_surface: null,
            tasks: [{ id: 500, name: 'A', order: 0, instructions: 'a', output_schema: {}, context_tasks: [] }],
        };
        // The deletion of task B (id 501) was saved; undo then brought B back with its old id.
        const loaded = mapAgentNodeToModel(savedAgent);
        const taskA = loaded.data.tasks[0];
        const baseline: FlowModel = { nodes: [loaded], connections: [] };
        const restoredTasks: AgentNodeTaskUi[] = [
            taskA,
            { ...task('t-b', 501), name: 'B' },
            { ...task('t-c', undefined, [{ id: 501 }]), name: 'C' },
        ];
        const canvas: FlowModel = {
            nodes: [{ ...loaded, data: { ...loaded.data, tasks: restoredTasks } }],
            connections: [],
        };
        const response = {
            agent_node_list: [
                {
                    ...savedAgent,
                    tasks: [
                        savedAgent.tasks[0],
                        { id: 600, name: 'B', order: 1, instructions: '', output_schema: {}, context_tasks: [] },
                        { id: 601, name: 'C', order: 2, instructions: '', output_schema: {}, context_tasks: [600] },
                    ],
                },
            ],
        } as unknown as GraphDto;

        it('sends the restored task as new, takes the server id into the baseline and then finds nothing stale', () => {
            const cleaned = clearStaleIds(baseline, canvas);
            const nodeDiff = getNodeDiff(baseline, cleaned);
            const idMap = buildUuidToBackendIdMap(cleaned.nodes);
            const connectionDiff = getConnectionDiff(baseline, cleaned, idMap);

            const payload = buildBulkSavePayload(1, nodeDiff, connectionDiff, cleaned, idMap, 1);
            const sentTasks = (payload['agent_node_list'] as { tasks: Record<string, unknown>[] }[])[0].tasks;
            expect(sentTasks[1]['id']).toBeUndefined();
            expect(sentTasks[1]['temp_id']).toBe('t-b');
            expect(sentTasks[2]['context_task_ids']).toEqual([]);
            expect(sentTasks[2]['context_task_temp_ids']).toEqual(['t-b']);

            const newBaseline = patchFlowStateWithBackendIds(cleaned, baseline, nodeDiff, response);
            const patchedTasks = tasksOf(newBaseline, loaded.id);
            expect(patchedTasks.map((t) => t.id)).toEqual([500, 600, 601]);
            expect(patchedTasks[2].contextRefs).toEqual([{ id: 600 }]);

            expect(clearStaleIds(newBaseline, newBaseline).nodes[0]).toBe(newBaseline.nodes[0]);
        });
    });
});
