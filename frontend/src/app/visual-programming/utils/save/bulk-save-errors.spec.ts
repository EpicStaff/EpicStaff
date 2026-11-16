import { NodeType } from '@shared/models';

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

/** Where the payload sent the item `matches` picks, as the backend's `index` would name it. */
function indexIn(listKey: string, matches: (item: Record<string, unknown>) => boolean): number {
    const index = (payload[listKey] as Record<string, unknown>[]).findIndex(matches);
    expect(index).toBeGreaterThanOrEqual(0);
    return index;
}

describe('mapBulkSaveErrors', () => {
    let createdTaskIndex: number;
    let updatedTaskIndex: number;

    beforeAll(() => {
        createdTaskIndex = indexIn('task_node_list', (item) => item['temp_id'] === newTask.id);
        updatedTaskIndex = indexIn('task_node_list', (item) => item['id'] === LIVE_NODE_ID.task);
    });

    it('places a created item on the node it was built from, and an updated one on the node holding its backend id', () => {
        const errors = {
            task_node_list: [
                { index: createdTaskIndex, errors: { output_variable_path: ["Path 'variables._x' is not allowed."] } },
                { index: updatedTaskIndex, errors: { instructions: ["Placeholder '{context._x}' is not allowed."] } },
            ],
        };

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
        const errors = {
            agent_node_list: [
                {
                    index: indexIn('agent_node_list', (item) => item['id'] === LIVE_NODE_ID.agent),
                    errors: {
                        tasks: [{ name: ['Too long.'] }, { instructions: ["Placeholder '{topic!r}' is not allowed."] }],
                    },
                },
            ],
        };

        const mapped = mapBulkSaveErrors(payload, errors, current.nodes);

        const [savedRow, newRow] = editedAgent.data.tasks;
        expect(mapped.byNodeId.get(savedAgent.id)).toEqual([
            {
                field: 'name',
                child: { list: 'tasks', key: agentTaskSaveErrorKey(savedRow), position: 0 },
                sentValue: 'Saved',
                messages: ['Too long.'],
            },
            {
                field: 'instructions',
                child: { list: 'tasks', key: agentTaskSaveErrorKey(newRow), position: 1 },
                sentValue: 'Say {topic!r}',
                messages: ["Placeholder '{topic!r}' is not allowed."],
            },
        ]);
    });

    it('keeps the prompt a nested error is about by its prompt key', () => {
        const tableIndex = indexIn(
            'classification_decision_table_node_list',
            (item) => item['id'] === LIVE_NODE_ID.classificationTable
        );
        const sentTable = (payload['classification_decision_table_node_list'] as Record<string, unknown>[])[tableIndex];
        const promptKeys = (sentTable['prompt_configs'] as Record<string, unknown>[]).map((sent) => sent['prompt_key']);
        const errors = {
            classification_decision_table_node_list: [
                {
                    index: tableIndex,
                    errors: {
                        prompt_configs: promptKeys.map((key) =>
                            key === 'extract' ? { prompt_text: ["Placeholder '{context._x}' is not allowed."] } : {}
                        ),
                    },
                },
            ],
        };

        const mapped = mapBulkSaveErrors(payload, errors, current.nodes);

        expect(mapped.byNodeId.get(savedTable.id)).toEqual([
            {
                field: 'prompt_text',
                child: { list: 'prompt_configs', key: 'extract', position: promptKeys.indexOf('extract') },
                sentValue: 'Pull {context._x}',
                messages: ["Placeholder '{context._x}' is not allowed."],
            },
        ]);
    });

    it.each([
        ['a plain message', 'id=6 not found in graph 1', [{ field: null, messages: ['id=6 not found in graph 1'] }]],
        ['a list of messages', ['Refused.'], [{ field: null, messages: ['Refused.'] }]],
        ['non-field errors', { non_field_errors: ['Refused.'] }, [{ field: null, messages: ['Refused.'] }]],
        [
            'a nested serializer, flattened onto its field',
            { inline_surface: { storage_items: [{ storage_file: ['Gone.'] }], name: ['Too long.'] } },
            [{ field: 'inline_surface', messages: ['Gone.', 'Too long.'] }],
        ],
        [
            'task-list messages that name no row',
            { tasks: ['Ensure this field has no more than 20 elements.'] },
            [{ field: 'tasks', messages: ['Ensure this field has no more than 20 elements.'] }],
        ],
        [
            'a task row error of no known shape',
            { tasks: ['Row one is wrong.', {}] },
            [{ field: 'tasks', messages: ['Row one is wrong.'] }],
        ],
    ])('keeps %s on the node as a whole or on its field', (_case, detail, expected) => {
        const agentIndex = indexIn('agent_node_list', (item) => item['id'] === LIVE_NODE_ID.agent);
        const errors = { agent_node_list: [{ index: agentIndex, errors: detail }] };

        const mapped = mapBulkSaveErrors(payload, errors, current.nodes).byNodeId.get(savedAgent.id);

        expect(mapped?.map(({ field, messages }) => ({ field, messages }))).toEqual(expected);
    });

    it.each([
        ['a body without errors', undefined, []],
        ['a plain message', 'Something went wrong', ['Something went wrong']],
        [
            'an edge error',
            { edge_list: ['Edge references node IDs not found in this graph: [9]'] },
            ['Edge references node IDs not found in this graph: [9]'],
        ],
        [
            'a graph-wide error',
            { nodes: ['This uuid is already used by another node of this flow.'] },
            ['This uuid is already used by another node of this flow.'],
        ],
        ['an item without an index', { task_node_list: [{ errors: { instructions: ['No index.'] } }] }, ['No index.']],
        [
            'an index past the sent list',
            { task_node_list: [{ index: 99, errors: { instructions: ['Past the list.'] } }] },
            ['Past the list.'],
        ],
        ['an unknown node list', { mystery_node_list: [{ index: 0, errors: 'Unknown list.' }] }, ['Unknown list.']],
    ])('places no node for %s and hands back its messages', (_case, errors, unplaced) => {
        const mapped = mapBulkSaveErrors(payload, errors, current.nodes);

        expect(mapped.byNodeId.size).toBe(0);
        expect(mapped.unplaced).toEqual(unplaced);
    });

    it('places nothing and hands back nothing for an item whose detail holds no message', () => {
        const errors = { task_node_list: [{ index: updatedTaskIndex, errors: {} }] };

        expect(mapBulkSaveErrors(payload, errors, current.nodes)).toEqual({ byNodeId: new Map(), unplaced: [] });
    });

    it('hands back what it could not place next to what it placed', () => {
        const errors = {
            task_node_list: [
                { index: updatedTaskIndex, errors: { instructions: ["Placeholder '{context._x}' is not allowed."] } },
                { index: 99, errors: { instructions: ['Past the list.'] } },
            ],
            edge_list: ['Edge references node IDs not found in this graph: [9]'],
            nodes: ['This uuid is already used by another node of this flow.'],
        };

        const mapped = mapBulkSaveErrors(payload, errors, current.nodes);

        expect([...mapped.byNodeId.keys()]).toEqual([savedTask.id]);
        expect(mapped.unplaced).toEqual([
            'Past the list.',
            'Edge references node IDs not found in this graph: [9]',
            'This uuid is already used by another node of this flow.',
        ]);
    });

    it('hands back the errors of an item whose node left the canvas', () => {
        const errors = { task_node_list: [{ index: createdTaskIndex, errors: { instructions: ['Gone.'] } }] };
        const withoutNewTask = current.nodes.filter((node) => node.id !== newTask.id);

        const mapped = mapBulkSaveErrors(payload, errors, withoutNewTask);

        expect(mapped.byNodeId.size).toBe(0);
        expect(mapped.unplaced).toEqual(['Gone.']);
    });

    it('never takes an edge id for a node backend id', () => {
        const edgePayload = { ...payload, edge_list: [{ id: LIVE_NODE_ID.task, graph: 1 }] };
        const errors = { edge_list: [{ index: 0, errors: { start_node_id: ['Invalid.'] } }] };

        const mapped = mapBulkSaveErrors(edgePayload, errors, current.nodes);

        expect(mapped.byNodeId.size).toBe(0);
        expect(mapped.unplaced).toEqual(['Invalid.']);
        expect(current.nodes.some((node) => node.type === NodeType.TASK && node.backendId === LIVE_NODE_ID.task)).toBe(
            true
        );
    });
});
