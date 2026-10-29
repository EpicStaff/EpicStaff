import { AuthorshipFields, UserSummary } from '@shared/models';

import { GraphDto } from '../../../features/flows/models/graph.model';
import { AgentNode } from '../../core/models/agent-node.model';
import { GetAudioToTextNodeRequest } from '../../core/models/audio-to-text.model';
import { GetClassificationDecisionTableNodeRequest } from '../../core/models/classification-decision-table-node.model';
import { GetDecisionTableNodeRequest } from '../../core/models/decision-table-node.model';
import { Edge } from '../../core/models/edge.model';
import { EndNode } from '../../core/models/end-node.model';
import { GetFileExtractorNodeRequest } from '../../core/models/file-extractor.model';
import { FlowModel } from '../../core/models/flow.model';
import { GraphNote } from '../../core/models/graph-note.model';
import { GetKeyValueNodeRequest } from '../../core/models/key-value-node.model';
import { GetKnowledgeRetrieverNodeRequest } from '../../core/models/knowledge-retriever-node.model';
import { PythonNode } from '../../core/models/python-node.model';
import { GetScheduleTriggerNodeRequest } from '../../core/models/schedule-trigger.model';
import { StartNode } from '../../core/models/start-node.model';
import { SubGraphNode } from '../../core/models/subgraph-node.model';
import { TaskNode } from '../../core/models/task-node.model';
import { GetTelegramTriggerNodeRequest } from '../../core/models/telegram-trigger.model';
import { GetWebhookTriggerNodeRequest } from '../../core/models/webhook-trigger';

// One node of every type the version export knows, as `GET /graphs/{id}/` returns it.
// Shared by the load (snapshot) and save (bulk-save payload) specs.

// Node ids are unique across node tables on the backend, so they are here too.
export const LIVE_NODE_ID = {
    start: 1,
    end: 2,
    note: 3,
    python: 4,
    task: 5,
    agent: 6,
    fileExtractor: 7,
    audio: 8,
    subgraph: 9,
    webhook: 10,
    telegram: 11,
    schedule: 12,
    decisionTable: 13,
    classificationTable: 14,
    knowledge: 15,
    keyValue: 16,
} as const;

/** Stable node uuids, as the backend returns them on every node. */
export const LIVE_NODE_UUID = {
    start: '00000000-0000-4000-8000-000000000001',
    end: '00000000-0000-4000-8000-000000000002',
    note: '00000000-0000-4000-8000-000000000003',
    python: '00000000-0000-4000-8000-000000000004',
    task: '00000000-0000-4000-8000-000000000005',
    agent: '00000000-0000-4000-8000-000000000006',
    fileExtractor: '00000000-0000-4000-8000-000000000007',
    audio: '00000000-0000-4000-8000-000000000008',
    subgraph: '00000000-0000-4000-8000-000000000009',
    webhook: '00000000-0000-4000-8000-000000000010',
    telegram: '00000000-0000-4000-8000-000000000011',
    schedule: '00000000-0000-4000-8000-000000000012',
    decisionTable: '00000000-0000-4000-8000-000000000013',
    classificationTable: '00000000-0000-4000-8000-000000000014',
    knowledge: '00000000-0000-4000-8000-000000000015',
    keyValue: '00000000-0000-4000-8000-000000000016',
} as const satisfies Record<keyof typeof LIVE_NODE_ID, string>;

const ID = LIVE_NODE_ID;

/** Id of the webhook trigger the webhook node references. */
export const LIVE_WEBHOOK_TRIGGER_ID = 77;

const author: UserSummary = {
    id: 7,
    display_name: 'Ada Lovelace',
    avatar_url: 'https://example.com/avatars/7.png',
};
// A user who never set a display name or an avatar.
const lastEditor: UserSummary = { id: 8, display_name: null, avatar_url: null };

/** Read-only authorship as the backend renders it on the graph and on every node. */
export const LIVE_AUTHORSHIP: AuthorshipFields = {
    created_by: author,
    last_edited_by: lastEditor,
    last_edited_at: '2026-01-02T00:00:00Z',
};

const authored = LIVE_AUTHORSHIP;
const persisted = { graph: 1, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' };
const nodeBase = { metadata: {}, input_map: {}, output_variable_path: null };

export const liveStart: StartNode = {
    ...authored,
    id: ID.start,
    uuid: LIVE_NODE_UUID.start,
    created_at: persisted.created_at,
    graph: 1,
    node_name: '__start__',
    variables: { topic: '' },
    metadata: {},
};
export const liveEnd: EndNode = {
    ...authored,
    id: ID.end,
    uuid: LIVE_NODE_UUID.end,
    created_at: persisted.created_at,
    graph: 1,
    node_name: '__end_node__',
    output_map: { answer: 'a' },
    metadata: {},
};
export const liveNote: GraphNote = {
    ...authored,
    id: ID.note,
    uuid: LIVE_NODE_UUID.note,
    created_at: persisted.created_at,
    graph: 1,
    node_name: 'Note',
    content: 'hello',
    metadata: {},
};
export const livePython: PythonNode = {
    ...nodeBase,
    ...authored,
    id: ID.python,
    uuid: LIVE_NODE_UUID.python,
    node_number: 1,
    graph: 1,
    created_at: persisted.created_at,
    node_name: 'Python',
    test_input: {},
    // The export has no python-code id; the preview uses 0.
    python_code: {
        id: 0,
        code: 'def main(): pass',
        entrypoint: 'main',
        secrets: [{ id: 101, name: 'API_KEY' }],
    },
};
export const liveTask: TaskNode = {
    ...nodeBase,
    ...authored,
    ...persisted,
    id: ID.task,
    uuid: LIVE_NODE_UUID.task,
    node_number: 2,
    node_name: 'Task',
    instructions: 'Do it',
    output_schema: {},
    remember_output: false,
    agent_definition: 41,
    surface_list: [51],
    inline_surface: {
        instructions: 'Be brief',
        python_tools: [{ python_tool: 21, mode: 'allow' }],
        mcp_tools: [{ mcp_tool: 31, mode: 'deny' }],
        storage_items: [],
        knowledge: [],
    },
};
export const liveAgent: AgentNode = {
    ...nodeBase,
    ...authored,
    id: ID.agent,
    uuid: LIVE_NODE_UUID.agent,
    node_number: 3,
    created_at: persisted.created_at,
    graph: 1,
    node_name: 'Agent',
    agent_definition: null, // FK nulled by the backend for a missing dependency: node kept
    surface_list: [],
    tasks: [],
    inline_surface: null,
};
export const liveFileExtractor: GetFileExtractorNodeRequest = {
    ...nodeBase,
    ...authored,
    id: ID.fileExtractor,
    uuid: LIVE_NODE_UUID.fileExtractor,
    node_number: 4,
    created_at: persisted.created_at,
    graph: 1,
    node_name: 'Files',
};
export const liveAudio: GetAudioToTextNodeRequest = {
    ...nodeBase,
    ...authored,
    id: ID.audio,
    uuid: LIVE_NODE_UUID.audio,
    node_number: 5,
    created_at: persisted.created_at,
    graph: 1,
    node_name: 'Audio',
};
export const liveSubgraph: SubGraphNode = {
    ...nodeBase,
    ...authored,
    id: ID.subgraph,
    uuid: LIVE_NODE_UUID.subgraph,
    node_number: 6,
    created_at: persisted.created_at,
    graph: 1,
    node_name: 'Sub',
    subgraph: 99,
};
export const liveWebhook: GetWebhookTriggerNodeRequest = {
    ...nodeBase,
    ...authored,
    id: ID.webhook,
    uuid: LIVE_NODE_UUID.webhook,
    node_number: 7,
    created_at: persisted.created_at,
    graph: 1,
    node_name: 'Webhook',
    webhook_trigger_path: '',
    webhook_trigger: LIVE_WEBHOOK_TRIGGER_ID, // a bare id, in the graph response and in the export alike
    python_code: { id: 0, code: 'def main(): pass', entrypoint: 'main', secrets: [] },
    test_payload: { id: '104' },
    use_storage: false,
};
export const liveTelegram: GetTelegramTriggerNodeRequest = {
    ...authored,
    id: ID.telegram,
    uuid: LIVE_NODE_UUID.telegram,
    node_number: 8,
    created_at: persisted.created_at,
    graph: 1,
    node_name: 'Telegram',
    metadata: {},
    telegram_bot_api_key_secret_id: 102,
    webhook_trigger: null,
    fields: [{ id: 1, parent: 'message', field_name: 'text', variable_path: 'variables.text' }],
    test_payload: { message: { text: 'hello' } },
};
const liveSchedule: GetScheduleTriggerNodeRequest = {
    ...persisted,
    ...authored,
    id: ID.schedule,
    uuid: LIVE_NODE_UUID.schedule,
    node_number: 9,
    node_name: 'Schedule',
    metadata: {},
    is_active: true,
    content_hash: '',
    current_runs: 2,
    schedule: {
        run_mode: 'repeat',
        timezone: 'Europe/Kyiv',
        start_date_time: '2026-07-01T12:00:00',
        next_run_date_time: null,
        interval: { every: 1, unit: 'hours', weekdays: [] },
        end: { type: 'on_date', date_time: '2026-12-01T12:00:00', max_runs: null },
    },
};
export const liveDecisionTable: GetDecisionTableNodeRequest = {
    ...authored,
    id: ID.decisionTable,
    uuid: LIVE_NODE_UUID.decisionTable,
    node_number: 10,
    created_at: persisted.created_at,
    graph: 1,
    node_name: 'Decide',
    metadata: {},
    default_next_node_id: ID.task,
    next_error_node_id: null,
    condition_groups: [
        {
            id: 1,
            decision_table_node: ID.decisionTable,
            group_name: 'yes',
            group_type: 'simple',
            expression: null,
            conditions: [{ id: 1, condition_group: 1, condition_name: 'always', condition: 'True' }],
            manipulation: null,
            next_node_id: ID.end,
            order: 1,
        },
    ],
};
export const liveClassificationTable: GetClassificationDecisionTableNodeRequest = {
    ...authored,
    id: ID.classificationTable,
    uuid: LIVE_NODE_UUID.classificationTable,
    node_number: 11,
    created_at: persisted.created_at,
    graph: 1,
    node_name: 'Classify',
    metadata: {},
    pre_python_code: {
        code: 'def main(): pass',
        entrypoint: 'main',
        global_kwargs: {},
        secrets: [{ id: 101, name: 'API_KEY' }],
    },
    pre_input_map: {},
    pre_output_variable_path: null,
    post_python_code: null,
    post_input_map: {},
    post_output_variable_path: null,
    pre_use_storage: false,
    post_use_storage: false,
    prompt_configs: [],
    default_llm_config: null,
    default_next_node_id: ID.end,
    next_error_node_id: null,
    condition_groups: [
        {
            id: 2,
            classification_decision_table_node: ID.classificationTable,
            group_name: 'route',
            order: 1,
            expression: null,
            prompt: null,
            manipulation: null,
            continue_flag: false,
            route_code: 'A',
            dock_visible: true,
            field_expressions: {},
            field_manipulations: {},
            next_node_id: ID.agent,
        },
    ],
};
export const liveKnowledge: GetKnowledgeRetrieverNodeRequest = {
    ...nodeBase,
    ...authored,
    ...persisted,
    id: ID.knowledge,
    uuid: LIVE_NODE_UUID.knowledge,
    node_number: 12,
    node_name: 'Knowledge',
    source_collection: 5,
    search_configs: { naive: { search_limit: 3, similarity_threshold: 0.7, is_suggested: false } },
    query: 'q',
    search_method: null,
    rag_type: 'naive',
    rag_id: 8,
    content_hash: null,
};
export const liveKeyValue: GetKeyValueNodeRequest = {
    ...nodeBase,
    ...authored,
    id: ID.keyValue,
    uuid: LIVE_NODE_UUID.keyValue,
    node_number: 13,
    created_at: persisted.created_at,
    graph: 1,
    node_name: 'Remember',
    key_value_table: 61,
    mode: 'write',
    entries: [{ key: 'customer', value: 'variables.customer' }],
};
export const liveEdges: Edge[] = [
    { id: 1, graph: 1, start_node_id: ID.start, end_node_id: ID.python, metadata: {} },
    { id: 2, graph: 1, start_node_id: ID.python, end_node_id: ID.decisionTable, metadata: {} },
    { id: 3, graph: 1, start_node_id: ID.task, end_node_id: ID.classificationTable, metadata: {} },
];

export const liveGraph: GraphDto = {
    ...authored,
    id: 1,
    uuid: 'graph-uuid',
    name: 'Flow',
    description: '',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-02T00:00:00Z',
    save_version: 3,
    node_number_seq: 13,
    // The API sends whatever metadata the canvas stored; an empty object is enough for the loaders.
    metadata: {} as FlowModel,
    start_node_list: [liveStart],
    end_node_list: [liveEnd],
    graph_note_list: [liveNote],
    python_node_list: [livePython],
    task_node_list: [liveTask],
    agent_node_list: [liveAgent],
    file_extractor_node_list: [liveFileExtractor],
    audio_transcription_node_list: [liveAudio],
    subgraph_node_list: [liveSubgraph],
    webhook_trigger_node_list: [liveWebhook],
    telegram_trigger_node_list: [liveTelegram],
    schedule_trigger_node_list: [liveSchedule],
    decision_table_node_list: [liveDecisionTable],
    classification_decision_table_node_list: [liveClassificationTable],
    knowledge_node_list: [liveKnowledge],
    key_value_node_list: [liveKeyValue],
    edge_list: liveEdges,
};
