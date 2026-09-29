import { NodeType } from '@shared/models';

import { GraphDto } from '../../../../features/flows/models/graph.model';
import {
    GraphVersionSnapshot,
    SnapshotNode,
    SnapshotNodeType,
} from '../../../../features/flows/models/graph-version-preview.model';
import { AgentNode } from '../../../core/models/agent-node.model';
import { GetAudioToTextNodeRequest } from '../../../core/models/audio-to-text.model';
import { GetClassificationDecisionTableNodeRequest } from '../../../core/models/classification-decision-table-node.model';
import { GetDecisionTableNodeRequest } from '../../../core/models/decision-table-node.model';
import { Edge } from '../../../core/models/edge.model';
import { EndNode } from '../../../core/models/end-node.model';
import { GetFileExtractorNodeRequest } from '../../../core/models/file-extractor.model';
import { FlowModel } from '../../../core/models/flow.model';
import { GraphNote } from '../../../core/models/graph-note.model';
import { GetKnowledgeRetrieverNodeRequest } from '../../../core/models/knowledge-retriever-node.model';
import { NodeModel } from '../../../core/models/node.model';
import { PythonNode } from '../../../core/models/python-node.model';
import { GetScheduleTriggerNodeRequest } from '../../../core/models/schedule-trigger.model';
import { StartNode } from '../../../core/models/start-node.model';
import { SubGraphNode } from '../../../core/models/subgraph-node.model';
import { TaskNode } from '../../../core/models/task-node.model';
import { GetTelegramTriggerNodeRequest } from '../../../core/models/telegram-trigger.model';
import { GetWebhookTriggerNodeRequest } from '../../../core/models/webhook-trigger';
import { buildFlowModelFromGraphDto } from '../build-flow-model-from-graph-dto';
import {
    buildPreviewFlowModel,
    mapSnapshotToGraphDto,
    SNAPSHOT_NODE_LIST_KEY,
    UnmappedGraphDtoNodeList,
} from './map-snapshot-to-graph-dto';
import { toLocalNaiveIso } from './snapshot-field-adapters';

// Node ids are unique across node tables on the backend, so they are here too.
const ID = {
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
} as const;

const secretsByName = new Map([
    ['API_KEY', 101],
    ['BOT_KEY', 102],
]);
const availableFlows = [{ id: 99 }];

// ── The same graph twice: as the live API returns it, and as the version export stores it ──

const persisted = { graph: 1, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' };
const nodeBase = { metadata: {}, input_map: {}, output_variable_path: null };

const liveStart: StartNode = { id: ID.start, graph: 1, node_name: '__start__', variables: { topic: '' }, metadata: {} };
const liveEnd: EndNode = { id: ID.end, graph: 1, node_name: '__end_node__', output_map: { answer: 'a' }, metadata: {} };
const liveNote: GraphNote = { id: ID.note, graph: 1, node_name: 'Note', content: 'hello', metadata: {} };
const livePython: PythonNode = {
    ...nodeBase,
    id: ID.python,
    graph: 1,
    node_name: 'Python',
    test_input: {},
    // The export has no python-code id; the preview uses 0.
    python_code: {
        id: 0,
        code: 'def main(): pass',
        entrypoint: 'main',
        libraries: ['requests', 'pandas'],
        secrets: [{ id: 101, name: 'API_KEY' }],
    },
};
const liveTask: TaskNode = {
    ...nodeBase,
    ...persisted,
    id: ID.task,
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
const liveAgent: AgentNode = {
    ...nodeBase,
    id: ID.agent,
    graph: 1,
    node_name: 'Agent',
    agent_definition: null, // FK nulled by the backend for a missing dependency: node kept
    surface_list: [],
    tasks: [],
    inline_surface: null,
};
const liveFileExtractor: GetFileExtractorNodeRequest = {
    ...nodeBase,
    id: ID.fileExtractor,
    graph: 1,
    node_name: 'Files',
};
const liveAudio: GetAudioToTextNodeRequest = { ...nodeBase, id: ID.audio, graph: 1, node_name: 'Audio' };
const liveSubgraph: SubGraphNode = { ...nodeBase, id: ID.subgraph, graph: 1, node_name: 'Sub', subgraph: 99 };
const liveWebhook: GetWebhookTriggerNodeRequest = {
    ...nodeBase,
    id: ID.webhook,
    graph: 1,
    node_name: 'Webhook',
    webhook_trigger_path: '',
    webhook_trigger: 77, // the export's bare id
    python_code: { id: 0, code: 'def main(): pass', entrypoint: 'main', libraries: [], secrets: [] },
};
const liveTelegram: GetTelegramTriggerNodeRequest = {
    id: ID.telegram,
    graph: 1,
    node_name: 'Telegram',
    metadata: {},
    telegram_bot_api_key_secret_id: 102,
    webhook_trigger: null,
    fields: [{ id: 1, parent: 'message', field_name: 'text', variable_path: 'variables.text' }],
};
const liveSchedule: GetScheduleTriggerNodeRequest = {
    ...persisted,
    id: ID.schedule,
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
const liveDecisionTable: GetDecisionTableNodeRequest = {
    id: ID.decisionTable,
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
const liveClassificationTable: GetClassificationDecisionTableNodeRequest = {
    id: ID.classificationTable,
    graph: 1,
    node_name: 'Classify',
    metadata: {},
    pre_python_code: {
        code: 'def main(): pass',
        entrypoint: 'main',
        libraries: ['numpy'],
        global_kwargs: {},
        secrets: [{ id: 101, name: 'API_KEY' }],
    },
    pre_input_map: {},
    pre_output_variable_path: null,
    post_python_code: null,
    post_input_map: {},
    post_output_variable_path: null,
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
const liveKnowledge: GetKnowledgeRetrieverNodeRequest = {
    ...nodeBase,
    ...persisted,
    id: ID.knowledge,
    node_name: 'Knowledge',
    source_collection: 5,
    search_configs: { naive: { search_limit: 3, similarity_threshold: 0.7, is_suggested: false } },
    query: 'q',
    search_method: null,
    rag_type: 'naive',
    rag_id: 8,
    content_hash: null,
};
const liveEdges: Edge[] = [
    { id: 1, graph: 1, start_node_id: ID.start, end_node_id: ID.python, metadata: {} },
    { id: 2, graph: 1, start_node_id: ID.python, end_node_id: ID.decisionTable, metadata: {} },
    { id: 3, graph: 1, start_node_id: ID.task, end_node_id: ID.classificationTable, metadata: {} },
];

const liveGraph = {
    id: 1,
    uuid: 'graph-uuid',
    name: 'Flow',
    description: '',
    save_version: 3,
    metadata: {},
    start_node_list: [liveStart],
    end_node_list: [liveEnd],
    graph_note_list: [liveNote],
    python_node_list: [livePython],
    task_node_list: [liveTask],
    agent_node_list: [liveAgent],
    llm_node_list: [],
    file_extractor_node_list: [liveFileExtractor],
    audio_transcription_node_list: [liveAudio],
    subgraph_node_list: [liveSubgraph],
    webhook_trigger_node_list: [liveWebhook],
    telegram_trigger_node_list: [liveTelegram],
    schedule_trigger_node_list: [liveSchedule],
    decision_table_node_list: [liveDecisionTable],
    classification_decision_table_node_list: [liveClassificationTable],
    knowledge_node_list: [liveKnowledge],
    edge_list: liveEdges,
    conditional_edge_list: [],
} as unknown as GraphDto;

/** What the export does to a row whose shape is otherwise identical: drop DB columns, tag the type. */
function exported<T extends object>(nodeType: SnapshotNodeType, row: T): SnapshotNode {
    const copy: Record<string, unknown> = { ...row, node_type: nodeType };
    delete copy['graph'];
    delete copy['created_at'];
    delete copy['updated_at'];
    return copy as unknown as SnapshotNode;
}

function exportedEdge(edge: Edge): Omit<Edge, 'graph'> {
    const copy: Partial<Edge> = { ...edge };
    delete copy.graph;
    return copy as Omit<Edge, 'graph'>;
}

const snapshot: GraphVersionSnapshot = {
    nodes: [
        exported('StartNode', liveStart),
        exported('EndNode', liveEnd),
        exported('GraphNote', liveNote),
        exported('PythonNode', {
            ...livePython,
            python_code: { code: 'def main(): pass', entrypoint: 'main', libraries: 'requests pandas' },
        }),
        exported('TaskNode', {
            ...liveTask,
            inline_surface: {
                instructions: 'Be brief',
                tools: {
                    PythonCodeTool: [{ python_tool_id: 21, mode: 'allow' }],
                    MCPTool: [{ mcp_tool_id: 31, mode: 'deny' }],
                },
            },
        }),
        exported('AgentNode', liveAgent),
        exported('FileExtractorNode', liveFileExtractor),
        exported('AudioTranscriptionNode', liveAudio),
        exported('SubgraphNode', liveSubgraph),
        exported('WebhookTriggerNode', {
            ...liveWebhook,
            webhook_trigger_path: undefined,
            python_code: { code: 'def main(): pass', entrypoint: 'main', libraries: '' },
        }),
        exported('TelegramTriggerNode', { ...liveTelegram, telegram_bot_api_key_secret_id: undefined }),
        {
            id: ID.schedule,
            node_type: 'ScheduleTriggerNode',
            node_name: 'Schedule',
            metadata: {},
            is_active: true,
            timezone: 'Europe/Kyiv',
            run_mode: 'repeat',
            start_date_time: '2026-07-01T09:00:00Z',
            every: 1,
            unit: 'hours',
            weekdays: [],
            end_type: 'on_date',
            end_date_time: '2026-12-01T10:00:00Z',
            max_runs: null,
            current_runs: 2,
            next_run_date_time: '2026-07-01T10:00:00Z',
        },
        exported('DecisionTableNode', liveDecisionTable),
        exported('ClassificationDecisionTableNode', {
            ...liveClassificationTable,
            pre_python_code: { code: 'def main(): pass', entrypoint: 'main', libraries: 'numpy', global_kwargs: {} },
        }),
        exported('KnowledgeNode', {
            ...liveKnowledge,
            search_configs: undefined,
            // The export writes the Decimal column as a string.
            naive_search_config: { search_limit: 3, similarity_threshold: '0.70', is_suggested: false },
        }),
    ],
    edge_list: liveEdges.map((edge) => exportedEdge(edge)),
    conditional_edge_list: [],
    metadata: {},
    secret_declarations: {
        nodes: {
            [ID.python]: { python_code: ['API_KEY', 'DELETED_SECRET'] },
            [ID.classificationTable]: { pre_python_code: ['API_KEY'] },
        },
        telegram: { [ID.telegram]: 'BOT_KEY' },
    },
};

/** Canvas ids are random; replace each by its order of first appearance. DB columns are not exported. */
function comparable(flow: FlowModel): unknown {
    const uuidPattern = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/g;
    const order = new Map<string, number>();
    const json = JSON.stringify(flow, (key, value: unknown) =>
        ['graph', 'created_at', 'updated_at'].includes(key) ? undefined : value
    ).replace(uuidPattern, (uuid) => {
        if (!order.has(uuid)) order.set(uuid, order.size);
        return `uuid-${order.get(uuid)}`;
    });
    return JSON.parse(json);
}

function nodeWithSnapshotId(flow: FlowModel, snapshotIdToNodeUuid: Map<number, string>, id: number): NodeModel {
    return flow.nodes.find((node) => node.id === snapshotIdToNodeUuid.get(id))!;
}

describe('mapSnapshotToGraphDto', () => {
    it('covers every snapshot node type (the fixture holds one of each)', () => {
        const fixtureTypes = snapshot.nodes.map((node) => node.node_type).sort();
        expect(Object.keys(SNAPSHOT_NODE_LIST_KEY).sort()).toEqual(fixtureTypes);
        expectTypeOf<UnmappedGraphDtoNodeList>().toBeNever();
    });

    it('puts each node type in its GraphDto list', () => {
        const graphDto = mapSnapshotToGraphDto(snapshot, secretsByName);

        for (const node of snapshot.nodes) {
            const list = graphDto[SNAPSHOT_NODE_LIST_KEY[node.node_type]] as { id: number }[];
            expect(list.map((item) => item.id)).toEqual([node.id]);
        }
    });
});

describe('buildPreviewFlowModel', () => {
    const { flow, snapshotIdToNodeUuid } = buildPreviewFlowModel(snapshot, secretsByName, availableFlows);
    const byId = (id: number): NodeModel => nodeWithSnapshotId(flow, snapshotIdToNodeUuid, id);

    it('equals the live loader result for the same graph (ignoring canvas ids)', () => {
        const liveFlow = buildFlowModelFromGraphDto(liveGraph, availableFlows);
        const detachedLiveFlow = { ...liveFlow, nodes: liveFlow.nodes.map((node) => ({ ...node, backendId: null })) };

        expect(comparable(flow)).toEqual(comparable(detachedLiveFlow));
    });

    it('detaches every node from the backend and maps every snapshot id to a canvas node', () => {
        expect(flow.nodes.every((node) => node.backendId === null)).toBe(true);
        expect([...snapshotIdToNodeUuid.keys()].sort((a, b) => a - b)).toEqual(Object.values(ID));
        expect(new Set(snapshotIdToNodeUuid.values())).toEqual(new Set(flow.nodes.map((node) => node.id)));
    });

    it('resolves declared secrets by name and leaves out ones the organisation no longer has', () => {
        const python = byId(ID.python).data as { secret_ids: number[]; secret_names: string[] };
        expect(python.secret_names).toEqual(['API_KEY']);
        expect(python.secret_ids).toEqual([101]);

        const telegram = byId(ID.telegram).data as { telegram_bot_api_key_secret_id: number | null };
        expect(telegram.telegram_bot_api_key_secret_id).toBe(102);
    });

    it('resolves decision-table references and connections to canvas ids', () => {
        const table = byId(ID.decisionTable).data as {
            table: { default_next_node: string; condition_groups: { next_node: string }[] };
        };
        expect(table.table.default_next_node).toBe(snapshotIdToNodeUuid.get(ID.task));
        expect(table.table.condition_groups[0].next_node).toBe(snapshotIdToNodeUuid.get(ID.end));

        const connected = (sourceId: number, targetId: number): boolean =>
            flow.connections.some(
                (connection) =>
                    connection.sourceNodeId === snapshotIdToNodeUuid.get(sourceId) &&
                    connection.targetNodeId === snapshotIdToNodeUuid.get(targetId)
            );
        expect(connected(ID.start, ID.python)).toBe(true);
        expect(connected(ID.decisionTable, ID.end)).toBe(true);
        expect(connected(ID.classificationTable, ID.agent)).toBe(true);
    });

    it('keeps inline surfaces, the webhook trigger id and a numeric similarity threshold', () => {
        expect((byId(ID.task).data as { inline_surface: unknown }).inline_surface).toEqual(liveTask.inline_surface);
        expect((byId(ID.webhook).data as { webhook_trigger: unknown }).webhook_trigger).toBe(77);
        const knowledge = byId(ID.knowledge).data as GetKnowledgeRetrieverNodeRequest;
        expect(knowledge.search_configs?.naive?.similarity_threshold).toBe(0.7);
    });

    it('keeps a node whose dependency the backend nulled', () => {
        const orphaned: GraphVersionSnapshot = {
            nodes: [exported('SubgraphNode', { ...liveSubgraph, subgraph: null })],
        };
        const result = buildPreviewFlowModel(orphaned, secretsByName, availableFlows);

        const subgraph = result.flow.nodes.find((node) => node.type === NodeType.SUBGRAPH);
        expect(subgraph?.isBlocked).toBe(true);
        expect(byId(ID.agent).data).toMatchObject({ agent_definition: null });
    });
});

// Expected values were produced by the backend helper itself —
// ScheduleTriggerValidator.format_utc_to_local_naive_iso, run via `make django-manage` — so the
// frontend port stays pinned to it.
describe('toLocalNaiveIso (schedule datetimes)', () => {
    it.each([
        ['Europe/Kyiv summer', '2026-07-01T09:00:00Z', 'Europe/Kyiv', '2026-07-01T12:00:00'],
        ['Europe/Kyiv winter', '2026-01-15T10:00:00Z', 'Europe/Kyiv', '2026-01-15T12:00:00'],
        ['UTC', '2026-07-01T09:00:00Z', 'UTC', '2026-07-01T09:00:00'],
        ['DST start, before the jump', '2026-03-29T00:30:00Z', 'Europe/Kyiv', '2026-03-29T02:30:00'],
        ['DST start, at the jump', '2026-03-29T01:00:00Z', 'Europe/Kyiv', '2026-03-29T04:00:00'],
        ['DST end, repeated hour', '2026-10-25T01:30:00Z', 'Europe/Kyiv', '2026-10-25T03:30:00'],
        ['non-Z offset', '2026-07-01T12:00:00+03:00', 'America/New_York', '2026-07-01T05:00:00'],
        ['fractional seconds', '2026-07-01T09:00:00.250000Z', 'Europe/Kyiv', '2026-07-01T12:00:00.250000'],
        ['unknown zone falls back to UTC', '2026-07-01T09:00:00Z', 'Not/AZone', '2026-07-01T09:00:00'],
    ])('%s', (_case, isoDateTime, timeZone, expected) => {
        expect(toLocalNaiveIso(isoDateTime, timeZone)).toBe(expected);
    });

    it('passes null through', () => {
        expect(toLocalNaiveIso(null, 'UTC')).toBeNull();
    });
});
