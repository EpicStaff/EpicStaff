import {
    GraphVersionSnapshot,
    SnapshotNode,
    SnapshotNodeType,
} from '../../../features/flows/models/graph-version-preview.model';
import { Edge } from '../../core/models/edge.model';
import {
    LIVE_AUTHORSHIP,
    LIVE_NODE_ID as ID,
    LIVE_NODE_UUID as UUID,
    liveAgent,
    liveAudio,
    liveClassificationTable,
    liveDecisionTable,
    liveEdges,
    liveEnd,
    liveFileExtractor,
    liveKeyValue,
    liveKnowledge,
    liveNote,
    livePython,
    liveStart,
    liveSubgraph,
    liveTask,
    liveTelegram,
    liveWebhook,
} from './live-graph.fixture';

// The version export of `liveGraph` (live-graph.fixture.ts): the same graph as a stored snapshot.
// Shared by the snapshot loader and the version diff specs.

/** The organisation's current secrets, by name (what the preview resolves declared names against). */
export const SNAPSHOT_SECRETS_BY_NAME: ReadonlyMap<string, number> = new Map([
    ['API_KEY', 101],
    ['BOT_KEY', 102],
]);

/** Flows the preview can see; the subgraph node's target is one of them. */
export const SNAPSHOT_AVAILABLE_FLOWS = [{ id: 99 }];

const authorshipFields = Object.keys(LIVE_AUTHORSHIP);

/** What the export does to a row whose shape is otherwise identical: drop DB columns and authorship, tag the type. */
export function exported<T extends object>(nodeType: SnapshotNodeType, row: T): SnapshotNode {
    const copy: Record<string, unknown> = { ...row, node_type: nodeType };
    for (const field of ['graph', 'created_at', 'updated_at', ...authorshipFields]) delete copy[field];
    return copy as unknown as SnapshotNode;
}

export function exportedEdge(edge: Edge): Omit<Edge, 'graph'> {
    const copy: Partial<Edge> = { ...edge };
    delete copy.graph;
    return copy as Omit<Edge, 'graph'>;
}

export const liveGraphSnapshot: GraphVersionSnapshot = {
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
            uuid: UUID.schedule,
            node_type: 'ScheduleTriggerNode',
            node_name: 'Schedule',
            node_number: 9,
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
        exported('KeyValueNode', { ...liveKeyValue, key_value_table_name: 'Customers' }),
    ],
    edge_list: liveEdges.map((edge) => exportedEdge(edge)),
    metadata: {},
    secret_declarations: {
        nodes: {
            [ID.python]: { python_code: ['API_KEY', 'DELETED_SECRET'] },
            [ID.classificationTable]: { pre_python_code: ['API_KEY'] },
        },
        telegram: { [ID.telegram]: 'BOT_KEY' },
    },
};
