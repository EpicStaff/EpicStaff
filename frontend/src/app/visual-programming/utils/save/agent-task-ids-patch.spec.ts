import { GraphDto } from '../../../features/flows/models/graph.model';
import { AgentNode, AgentNodeTaskUi } from '../../core/models/agent-node.model';
import { FlowModel } from '../../core/models/flow.model';
import { AgentNodeModel } from '../../core/models/node.model';
import { mapAgentNodeToModel } from '../load/nodes/agent-node.mapper';
import { getNodeDiff } from './diff';
import { patchFlowStateWithBackendIds, patchLiveFlowWithBackendIds } from './patch';

/**
 * Agent task ids a save hands out: by position for the flow that was sent, by
 * `tempId` for the live canvas, which may have changed while the save was in flight.
 */

const SAVED_AGENT: AgentNode = {
    uuid: '00000000-0000-4000-8000-000000000045',
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    last_edited_by: null,
    last_edited_at: null,
    id: 50,
    metadata: {},
    node_name: 'Agent #1',
    input_map: {},
    output_variable_path: null,
    agent_definition: 3,
    surface_list: [],
    inline_surface: null,
    tasks: [{ id: 500, name: 'Existing', order: 0, instructions: 'Do it', output_schema: {}, context_tasks: [] }],
};

function newTask(tempId: string, contextRefs: AgentNodeTaskUi['contextRefs'] = []): AgentNodeTaskUi {
    return { tempId, name: tempId, instructions: `Run ${tempId}`, output_schema: {}, contextRefs };
}

function withTasks(node: AgentNodeModel, tasks: AgentNodeTaskUi[]): AgentNodeModel {
    return { ...node, data: { ...node.data, tasks } };
}

function flow(node: AgentNodeModel): FlowModel {
    return { nodes: [node], connections: [] };
}

function tasksOf(patched: FlowModel): Pick<AgentNodeTaskUi, 'tempId' | 'id' | 'contextRefs'>[] {
    return (patched.nodes[0] as AgentNodeModel).data.tasks.map(({ tempId, id, contextRefs }) => ({
        tempId,
        id,
        contextRefs,
    }));
}

describe('agent task ids from a save response', () => {
    const loaded = mapAgentNodeToModel(SAVED_AGENT);
    const existing = loaded.data.tasks[0];
    // Sent: the existing task, then a new one that refers to it... and one referring to the new one.
    const sent = withTasks(loaded, [existing, newTask('a'), newTask('b', [{ tempId: 'a' }])]);
    const response = {
        agent_node_list: [
            {
                ...SAVED_AGENT,
                tasks: [
                    { ...SAVED_AGENT.tasks[0], order: 0 },
                    { id: 501, name: 'a', order: 1, instructions: 'Run a', output_schema: {}, context_tasks: [] },
                    { id: 502, name: 'b', order: 2, instructions: 'Run b', output_schema: {}, context_tasks: [501] },
                ],
            },
        ],
    } as unknown as GraphDto;
    const previous = flow(loaded);
    const nodeDiff = getNodeDiff(previous, flow(sent));
    const sentPatched = patchFlowStateWithBackendIds(flow(sent), previous, nodeDiff, response);

    it('gives the sent flow its new tasks’ ids by position, and resolves refs between them', () => {
        expect(tasksOf(sentPatched)).toEqual([
            { tempId: existing.tempId, id: 500, contextRefs: [] },
            { tempId: 'a', id: 501, contextRefs: [] },
            { tempId: 'b', id: 502, contextRefs: [{ id: 501 }] },
        ]);
    });

    it('gives the sent flow its ids by position alone, whatever its tempIds — duplicated or empty', () => {
        const odd = withTasks(loaded, [existing, newTask('dup'), newTask('dup'), newTask('')]);
        const oddResponse = {
            agent_node_list: [
                {
                    ...SAVED_AGENT,
                    tasks: [501, 502, 503].map((id, index) => ({
                        id,
                        name: `task ${id}`,
                        order: index + 1,
                        instructions: 'Run',
                        output_schema: {},
                        context_tasks: [],
                    })),
                },
            ],
        } as unknown as GraphDto;

        const patched = patchFlowStateWithBackendIds(
            flow(odd),
            previous,
            getNodeDiff(previous, flow(odd)),
            oddResponse
        );

        expect(tasksOf(patched).map((task) => task.id)).toEqual([500, 501, 502, 503]);
    });

    it('gives the live canvas the same ids by tempId when a task was inserted before them meanwhile', () => {
        const live = withTasks(sent, [newTask('inserted'), existing, newTask('a'), newTask('b', [{ tempId: 'a' }])]);

        const patched = patchLiveFlowWithBackendIds(flow(live), sentPatched, previous, nodeDiff, response);

        expect(tasksOf(patched)).toEqual([
            { tempId: 'inserted', id: undefined, contextRefs: [] },
            { tempId: existing.tempId, id: 500, contextRefs: [] },
            { tempId: 'a', id: 501, contextRefs: [] },
            { tempId: 'b', id: 502, contextRefs: [{ id: 501 }] },
        ]);
    });

    it('follows tasks that were reordered or removed meanwhile, never handing one another’s id', () => {
        const live = withTasks(sent, [newTask('b', [{ tempId: 'a' }]), existing]);

        const patched = patchLiveFlowWithBackendIds(flow(live), sentPatched, previous, nodeDiff, response);

        // `a` was removed: `b` gets its own id, and its ref to `a` stays unresolved rather than taking a wrong id.
        expect(tasksOf(patched)).toEqual([
            { tempId: 'b', id: 502, contextRefs: [{ tempId: 'a' }] },
            { tempId: existing.tempId, id: 500, contextRefs: [] },
        ]);
    });
});
