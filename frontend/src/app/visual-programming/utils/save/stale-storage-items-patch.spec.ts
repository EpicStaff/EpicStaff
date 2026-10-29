import { GraphDto } from '../../../features/flows/models/graph.model';
import { AgentNode } from '../../core/models/agent-node.model';
import { FlowModel } from '../../core/models/flow.model';
import { AgentNodeModel, TaskNodeModel } from '../../core/models/node.model';
import { InlineSurface, TaskNode } from '../../core/models/task-node.model';
import { mapAgentNodeToModel } from '../load/nodes/agent-node.mapper';
import { mapTaskNodeToModel } from '../load/nodes/task-node.mapper';
import { getNodeDiff } from './diff';
import { patchFlowStateWithBackendIds, patchLiveFlowWithBackendIds } from './patch';

/**
 * A save response can omit an inline-surface storage item the server dropped (its file was
 * binned). The editor must forget exactly those items, on the sent baseline and on the live
 * canvas alike, and nothing else.
 */

const FILE_KEPT = 11;
const FILE_BINNED = 12;
const FILE_ADDED_MEANWHILE = 13;

function storageItem(storageFile: number): InlineSurface['storage_items'][number] {
    return { storage_file: storageFile, can_list: 'allow', can_view: 'allow', can_edit: 'unset', can_delete: 'unset' };
}

function surface(...files: number[]): InlineSurface {
    return {
        instructions: 'Be brief',
        python_tools: [],
        mcp_tools: [],
        storage_items: files.map(storageItem),
        knowledge: [],
    };
}

const SAVED_AGENT = {
    id: 50,
    node_number: 1,
    node_name: 'Agent',
    metadata: {},
    input_map: {},
    output_variable_path: null,
    agent_definition: 3,
    surface_list: [],
    tasks: [],
    inline_surface: surface(FILE_KEPT, FILE_BINNED),
} as unknown as AgentNode;

const SAVED_TASK = {
    id: 60,
    node_number: 2,
    node_name: 'Task',
    metadata: {},
    input_map: {},
    output_variable_path: null,
    instructions: 'Do it',
    output_schema: {},
    remember_output: false,
    agent_definition: 3,
    surface_list: [],
    inline_surface: surface(FILE_KEPT, FILE_BINNED),
} as unknown as TaskNode;

const UNSENT_TASK = {
    ...SAVED_TASK,
    id: 61,
    node_number: 3,
    node_name: 'Untouched task',
} as unknown as TaskNode;

/** The nodes as the server holds them after it dropped the binned file's item. */
function responseWith(overrides: { agent?: Partial<AgentNode>; task?: Partial<TaskNode> } = {}): GraphDto {
    return {
        agent_node_list: [{ ...SAVED_AGENT, inline_surface: surface(FILE_KEPT), ...overrides.agent }],
        task_node_list: [{ ...SAVED_TASK, inline_surface: surface(FILE_KEPT), ...overrides.task }],
    } as unknown as GraphDto;
}

function withSurface<T extends AgentNodeModel | TaskNodeModel>(node: T, inlineSurface: InlineSurface | null): T {
    return { ...node, data: { ...node.data, inline_surface: inlineSurface } };
}

function filesOf(node: AgentNodeModel | TaskNodeModel): number[] | undefined {
    return node.data.inline_surface?.storage_items.map((item) => item.storage_file);
}

describe('stale inline-surface storage items after a save', () => {
    const agent = mapAgentNodeToModel(SAVED_AGENT);
    const task = mapTaskNodeToModel(SAVED_TASK);
    const unsentTask = mapTaskNodeToModel(UNSENT_TASK);

    const previous: FlowModel = { nodes: [agent, task, unsentTask], connections: [] };
    // Both nodes are edited so they land in the diff's toUpdate and are sent with the binned item.
    const sentAgent = { ...agent, node_name: 'Agent edited' };
    const sentTask = { ...task, node_name: 'Task edited' };
    const sent: FlowModel = { nodes: [sentAgent, sentTask, unsentTask], connections: [] };
    const nodeDiff = getNodeDiff(previous, sent);

    function savedFlows(response: GraphDto, live: FlowModel = sent) {
        const sentPatched = patchFlowStateWithBackendIds(sent, previous, nodeDiff, response);
        const livePatched = patchLiveFlowWithBackendIds(live, sentPatched, previous, nodeDiff, response);
        return { sentPatched, livePatched };
    }

    it.each([
        ['agent', 0],
        ['task', 1],
    ])('prunes the dropped item from the sent baseline and the live canvas of the %s node', (_label, index) => {
        const { sentPatched, livePatched } = savedFlows(responseWith());

        for (const flow of [sentPatched, livePatched]) {
            const node = flow.nodes[index] as AgentNodeModel | TaskNodeModel;
            expect(filesOf(node)).toEqual([FILE_KEPT]);
            expect(node.data.inline_surface?.instructions).toBe('Be brief');
        }
    });

    it('prunes the item on a freshly created node, which the response numbers with its own id', () => {
        const brandNew = withSurface(
            { ...task, id: 'new-task-uuid', backendId: null },
            surface(FILE_KEPT, FILE_BINNED)
        );
        const emptyFlow: FlowModel = { nodes: [], connections: [] };
        const createFlow: FlowModel = { nodes: [brandNew], connections: [] };
        const createDiff = getNodeDiff(emptyFlow, createFlow);

        const patched = patchFlowStateWithBackendIds(createFlow, emptyFlow, createDiff, responseWith());

        expect(patched.nodes[0].backendId).toBe(60);
        expect(filesOf(patched.nodes[0] as TaskNodeModel)).toEqual([FILE_KEPT]);
    });

    it('keeps an item added on the live canvas while the save was in flight', () => {
        const live: FlowModel = {
            nodes: [
                withSurface(sentAgent, surface(FILE_KEPT, FILE_BINNED, FILE_ADDED_MEANWHILE)),
                withSurface(sentTask, surface(FILE_KEPT, FILE_BINNED, FILE_ADDED_MEANWHILE)),
                unsentTask,
            ],
            connections: [],
        };

        const { sentPatched, livePatched } = savedFlows(responseWith(), live);

        expect(filesOf(livePatched.nodes[0] as AgentNodeModel)).toEqual([FILE_KEPT, FILE_ADDED_MEANWHILE]);
        expect(filesOf(livePatched.nodes[1] as TaskNodeModel)).toEqual([FILE_KEPT, FILE_ADDED_MEANWHILE]);
        expect(filesOf(sentPatched.nodes[0] as AgentNodeModel)).toEqual([FILE_KEPT]);
    });

    it('returns the very same task node when nothing it sent was dropped, and an equal agent node', () => {
        const untouchedResponse = responseWith({
            agent: { inline_surface: surface(FILE_KEPT, FILE_BINNED) },
            task: { inline_surface: surface(FILE_KEPT, FILE_BINNED) },
        });

        const { sentPatched, livePatched } = savedFlows(untouchedResponse);

        for (const flow of [sentPatched, livePatched]) {
            // Agent nodes are rebuilt by the task-id patch anyway, so only their content is pinned.
            expect(flow.nodes[0]).toEqual(sentAgent);
            expect(flow.nodes[1]).toBe(sentTask);
        }
    });

    it('leaves the live canvas equal to the sent baseline when nothing changed since the save', () => {
        const { sentPatched, livePatched } = savedFlows(responseWith());

        expect(livePatched).toEqual(sentPatched);
    });

    it('prunes a single-node save, whose diff covers one node while the baseline holds several', () => {
        const singleDiff = getNodeDiff({ nodes: [task], connections: [] }, { nodes: [sentTask], connections: [] });
        const response = responseWith();

        const sentPatched = patchFlowStateWithBackendIds(sent, previous, singleDiff, response);
        const livePatched = patchLiveFlowWithBackendIds(sent, sentPatched, previous, singleDiff, response);

        for (const flow of [sentPatched, livePatched]) {
            expect(filesOf(flow.nodes[1] as TaskNodeModel)).toEqual([FILE_KEPT]);
            expect(flow.nodes[0]).toEqual(sentAgent);
            expect(flow.nodes[2]).toEqual(unsentTask);
        }
    });

    it('leaves a node that was not sent alone, even if the response lacks its items', () => {
        const response = {
            ...responseWith(),
            task_node_list: [
                { ...SAVED_TASK, inline_surface: surface(FILE_KEPT) },
                { ...UNSENT_TASK, inline_surface: surface() },
            ],
        } as unknown as GraphDto;

        const { sentPatched, livePatched } = savedFlows(response);

        expect(sentPatched.nodes[2]).toEqual(unsentTask);
        expect(livePatched.nodes[2]).toEqual(unsentTask);
    });

    it('prunes every sent item but keeps the surface when the response carries no surface', () => {
        const { livePatched } = savedFlows(responseWith({ task: { inline_surface: null } }));

        const patchedTask = livePatched.nodes[1] as TaskNodeModel;
        expect(patchedTask.data.inline_surface).not.toBeNull();
        expect(filesOf(patchedTask)).toEqual([]);
        expect(patchedTask.data.inline_surface?.instructions).toBe('Be brief');
    });

    it('does nothing for a sent node the response does not list', () => {
        const response = { agent_node_list: [], task_node_list: [] } as unknown as GraphDto;

        const { livePatched } = savedFlows(response);

        expect(livePatched.nodes[0]).toEqual(sentAgent);
        expect(livePatched.nodes[1]).toEqual(sentTask);
    });
});
