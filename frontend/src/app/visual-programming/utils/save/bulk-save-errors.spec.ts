import { ApiErrorDetail, NodeType } from '@shared/models';
import { toApiErrors } from '@shared/utils';

import { PromptConfig } from '../../core/models/classification-decision-table.model';
import { FlowModel } from '../../core/models/flow.model';
import {
    AgentNodeModel,
    ClassificationDecisionTableNodeModel,
    NodeModel,
    TaskNodeModel,
} from '../../core/models/node.model';
import { buildFlowModelFromGraphDto } from '../load';
import { LIVE_NODE_ID, liveGraph } from '../testing/live-graph.fixture';
import { agentTaskSaveErrorKey, mapBulkSaveErrors } from './bulk-save-errors';
import { buildUuidToBackendIdMap, getNodeDiff } from './diff';
import { buildBulkSavePayload } from './payload';

/**
 * A refused bulk save names an item by its index in the list that was sent; the editor needs the canvas node
 * (and, inside it, the agent task or CDT prompt) the item was built from. The payloads here come from the real
 * `buildBulkSavePayload`, so the indexes are the ones the backend would see.
 */

const loaded = buildFlowModelFromGraphDto(liveGraph);

function loadedNode<T extends NodeModel>(backendId: number): T {
    return loaded.nodes.find((node) => node.backendId === backendId) as T;
}

const prompt = (prompt_text: string): PromptConfig => ({
    prompt_text,
    llm_config: null,
    output_schema: {},
    result_variable: 'result',
    variable_mappings: {},
});

const savedTask = loadedNode<TaskNodeModel>(LIVE_NODE_ID.task);
const editedTask: TaskNodeModel = { ...savedTask, data: { ...savedTask.data, instructions: 'Use {context._x}' } };
const newTask: TaskNodeModel = { ...savedTask, id: 'new-task', backendId: null, node_name: 'New task' };
const savedAgent = loadedNode<AgentNodeModel>(LIVE_NODE_ID.agent);
const editedAgent: AgentNodeModel = {
    ...savedAgent,
    data: {
        ...savedAgent.data,
        tasks: [
            { id: 600, tempId: 'saved-row', name: 'Saved', instructions: 'Fine', output_schema: {}, contextRefs: [] },
            { tempId: 'new-row', name: 'New', instructions: 'Say {topic!r}', output_schema: {}, contextRefs: [] },
        ],
    },
};
const savedTable = loadedNode<ClassificationDecisionTableNodeModel>(LIVE_NODE_ID.classificationTable);
const editedTable: ClassificationDecisionTableNodeModel = {
    ...savedTable,
    data: {
        ...savedTable.data,
        table: {
            ...savedTable.data.table,
            prompts: { classify: prompt('Fine'), extract: prompt('Pull {context._x}') },
        },
    },
};

const current: FlowModel = {
    nodes: [
        ...loaded.nodes.map((node) =>
            node.id === savedTask.id
                ? editedTask
                : node.id === savedAgent.id
                  ? editedAgent
                  : node.id === savedTable.id
                    ? editedTable
                    : node
        ),
        newTask,
    ],
    connections: loaded.connections,
};
const idMap = buildUuidToBackendIdMap(current.nodes);
const payload = buildBulkSavePayload(
    1,
    getNodeDiff(loaded, current),
    { toCreate: [], toUpdate: [], toDelete: [] },
    current,
    idMap,
    1
);

/** The errors of a refused save in the error envelope, one `{code, detail, attr}` per message. */
function envelopeBody(...errors: [attr: string | null, detail: string][]): ApiErrorDetail[] {
    return toApiErrors({
        type: 'client_error',
        errors: errors.map(([attr, detail]) => ({ code: 'invalid', detail, attr, context: null })),
    });
}

/** Where the payload sent the item `matches` picks, as an error's `attr` names its index. */
function indexIn(listKey: string, matches: (item: Record<string, unknown>) => boolean): number {
    const index = (payload[listKey] as Record<string, unknown>[]).findIndex(matches);
    expect(index).toBeGreaterThanOrEqual(0);
    return index;
}

describe('mapBulkSaveErrors', () => {
    let createdTaskIndex: number;
    let updatedTaskIndex: number;
    let agentIndex: number;

    beforeAll(() => {
        createdTaskIndex = indexIn('task_node_list', (item) => item['temp_id'] === newTask.id);
        updatedTaskIndex = indexIn('task_node_list', (item) => item['id'] === LIVE_NODE_ID.task);
        agentIndex = indexIn('agent_node_list', (item) => item['id'] === LIVE_NODE_ID.agent);
    });

    it('places a created item on the node it was built from, and an updated one on the node holding its backend id', () => {
        const errors = envelopeBody(
            [`task_node_list.${createdTaskIndex}.output_variable_path`, "Path 'variables._x' is not allowed."],
            [`task_node_list.${updatedTaskIndex}.instructions`, "Placeholder '{context._x}' is not allowed."]
        );

        const mapped = mapBulkSaveErrors(payload, errors, current.nodes);

        expect(mapped.byNodeId.get(newTask.id)).toEqual([
            { field: 'output_variable_path', sentValue: null, messages: ["Path 'variables._x' is not allowed."] },
        ]);
        expect(mapped.byNodeId.get(savedTask.id)).toEqual([
            {
                field: 'instructions',
                sentValue: 'Use {context._x}',
                messages: ["Placeholder '{context._x}' is not allowed."],
            },
        ]);
    });

    it('keeps the agent task a nested error is about: a saved task by its id, a new one by its temp id', () => {
        const [savedRow, newRow] = editedAgent.data.tasks;
        const errors = envelopeBody(
            [`agent_node_list.${agentIndex}.non_field_errors`, 'Refused.'],
            [`agent_node_list.${agentIndex}.tasks.0.name`, 'Too long.'],
            [`agent_node_list.${agentIndex}.tasks.0.name`, 'Not unique.'],
            [`agent_node_list.${agentIndex}.tasks.1.non_field_errors`, 'Invalid data.'],
            [`agent_node_list.${agentIndex}.tasks.1.instructions`, "Placeholder '{topic!r}' is not allowed."],
            [`agent_node_list.${agentIndex}.inline_surface.storage_items.0.storage_file`, 'Gone.']
        );

        const mapped = mapBulkSaveErrors(payload, errors, current.nodes);

        expect(mapped.byNodeId.get(savedAgent.id)).toEqual([
            { field: null, messages: ['Refused.'] },
            {
                field: 'name',
                child: { list: 'tasks', key: agentTaskSaveErrorKey(savedRow), position: 0 },
                sentValue: 'Saved',
                messages: ['Too long.', 'Not unique.'],
            },
            {
                field: null,
                child: { list: 'tasks', key: agentTaskSaveErrorKey(newRow), position: 1 },
                messages: ['Invalid data.'],
            },
            {
                field: 'instructions',
                child: { list: 'tasks', key: agentTaskSaveErrorKey(newRow), position: 1 },
                sentValue: 'Say {topic!r}',
                messages: ["Placeholder '{topic!r}' is not allowed."],
            },
            { field: 'inline_surface', sentValue: null, messages: ['Gone.'] },
        ]);
        expect(mapped.unplaced).toEqual([]);
    });

    it('keeps the prompt a nested error is about by its prompt key', () => {
        const tableIndex = indexIn(
            'classification_decision_table_node_list',
            (item) => item['id'] === LIVE_NODE_ID.classificationTable
        );
        const sentTable = (payload['classification_decision_table_node_list'] as Record<string, unknown>[])[tableIndex];
        const promptKeys = (sentTable['prompt_configs'] as Record<string, unknown>[]).map((sent) => sent['prompt_key']);
        const extractPosition = promptKeys.indexOf('extract');
        const errors = envelopeBody([
            `classification_decision_table_node_list.${tableIndex}.prompt_configs.${extractPosition}.prompt_text`,
            "Placeholder '{context._x}' is not allowed.",
        ]);

        const mapped = mapBulkSaveErrors(payload, errors, current.nodes);

        expect(mapped.byNodeId.get(savedTable.id)).toEqual([
            {
                field: 'prompt_text',
                child: { list: 'prompt_configs', key: 'extract', position: extractPosition },
                sentValue: 'Pull {context._x}',
                messages: ["Placeholder '{context._x}' is not allowed."],
            },
        ]);
    });

    it.each<[string, [path: string, detail: string][], { field: string | null; messages: string[] }[]]>([
        [
            'an error naming only the item',
            [['', 'id=6 not found in graph 1']],
            [{ field: null, messages: ['id=6 not found in graph 1'] }],
        ],
        [
            'errors of a nested serializer, flattened onto its field',
            [
                ['.inline_surface.storage_items.0.storage_file', 'Gone.'],
                ['.inline_surface.name', 'Too long.'],
            ],
            [{ field: 'inline_surface', messages: ['Gone.', 'Too long.'] }],
        ],
        [
            'task-list messages that name no row',
            [['.tasks', 'Ensure this field has no more than 20 elements.']],
            [{ field: 'tasks', messages: ['Ensure this field has no more than 20 elements.'] }],
        ],
        [
            'the error of a task row that was not sent',
            [['.tasks.2.name', 'Row three is wrong.']],
            [{ field: 'tasks', messages: ['Row three is wrong.'] }],
        ],
    ])('keeps %s on the node as a whole or on its field', (_case, itemErrors, expected) => {
        const errors = envelopeBody(
            ...itemErrors.map(([path, detail]): [string, string] => [`agent_node_list.${agentIndex}${path}`, detail])
        );

        const mapped = mapBulkSaveErrors(payload, errors, current.nodes).byNodeId.get(savedAgent.id);

        expect(mapped?.map(({ field, messages }) => ({ field, messages }))).toEqual(expected);
    });

    it.each<[string, string | null]>([
        ['an error of the graph as a whole', null],
        ['an edge error', 'edge_list.0.start_node_id'],
        ['a graph-wide field error', 'nodes'],
        ['an unknown node list', 'mystery_node_list.0'],
        ['an item whose place is not a number', 'task_node_list.first.instructions'],
        ['a list path with no index', 'task_node_list'],
        ['an index past the sent list', 'task_node_list.99.instructions'],
    ])('places no node for %s and hands back its message', (_case, attr) => {
        const mapped = mapBulkSaveErrors(payload, envelopeBody([attr, 'Refused.']), current.nodes);

        expect(mapped.byNodeId.size).toBe(0);
        expect(mapped.unplaced).toEqual(['Refused.']);
    });

    it('hands back what it could not place next to what it placed, in the order the errors came', () => {
        const errors = envelopeBody(
            [`task_node_list.${updatedTaskIndex}.instructions`, "Placeholder '{context._x}' is not allowed."],
            ['task_node_list.99.instructions', 'Past the list.'],
            ['edge_list', 'Edge references node IDs not found in this graph: [9]'],
            [null, 'The flow is locked.']
        );

        const mapped = mapBulkSaveErrors(payload, errors, current.nodes);

        expect([...mapped.byNodeId.keys()]).toEqual([savedTask.id]);
        expect(mapped.unplaced).toEqual([
            'Past the list.',
            'Edge references node IDs not found in this graph: [9]',
            'The flow is locked.',
        ]);
    });

    it('places nothing and hands back nothing for an error whose detail is blank', () => {
        const errors = envelopeBody([`task_node_list.${updatedTaskIndex}.instructions`, '  ']);

        expect(mapBulkSaveErrors(payload, errors, current.nodes)).toEqual({
            byNodeId: new Map(),
            unplaced: [],
        });
    });

    it('hands back the errors of an item whose node left the canvas', () => {
        const errors = envelopeBody([`task_node_list.${createdTaskIndex}.instructions`, 'Gone.']);
        const withoutNewTask = current.nodes.filter((node) => node.id !== newTask.id);

        const mapped = mapBulkSaveErrors(payload, errors, withoutNewTask);

        expect(mapped.byNodeId.size).toBe(0);
        expect(mapped.unplaced).toEqual(['Gone.']);
    });

    it('never takes an edge id for a node backend id', () => {
        const edgePayload = { ...payload, edge_list: [{ id: LIVE_NODE_ID.task, graph: 1 }] };
        const errors = envelopeBody(['edge_list.0.start_node_id', 'Invalid.']);

        const mapped = mapBulkSaveErrors(edgePayload, errors, current.nodes);

        expect(mapped.byNodeId.size).toBe(0);
        expect(mapped.unplaced).toEqual(['Invalid.']);
        expect(current.nodes.some((node) => node.type === NodeType.TASK && node.backendId === LIVE_NODE_ID.task)).toBe(
            true
        );
    });
});
