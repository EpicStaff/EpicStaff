import { NodeType } from '@shared/models';

import {
    GraphVersionSnapshot,
    SnapshotNode,
    SnapshotNodeType,
} from '../../../../features/flows/models/graph-version-preview.model';
import { Edge } from '../../../core/models/edge.model';
import { FlowModel } from '../../../core/models/flow.model';
import { GetKnowledgeRetrieverNodeRequest } from '../../../core/models/knowledge-retriever-node.model';
import { KeyValueNodeModel, NodeModel } from '../../../core/models/node.model';
import {
    LIVE_AUTHORSHIP,
    LIVE_NODE_ID as ID,
    LIVE_WEBHOOK_TRIGGER_ID,
    liveAgent,
    liveAudio,
    liveClassificationTable,
    liveDecisionTable,
    liveEdges,
    liveEnd,
    liveFileExtractor,
    liveGraph,
    liveKeyValue,
    liveKnowledge,
    liveNote,
    livePython,
    liveStart,
    liveSubgraph,
    liveTask,
    liveTelegram,
    liveWebhook,
} from '../../testing/live-graph.fixture';
import { buildFlowModelFromGraphDto } from '../build-flow-model-from-graph-dto';
import {
    buildPreviewFlowModel,
    mapSnapshotToGraphDto,
    SNAPSHOT_NODE_LIST_KEY,
    UnmappedGraphDtoNodeList,
} from './map-snapshot-to-graph-dto';
import { toLocalNaiveIso } from './snapshot-field-adapters';

const secretsByName = new Map([
    ['API_KEY', 101],
    ['BOT_KEY', 102],
]);
const availableFlows = [{ id: 99 }];

// The live API side of the comparison is `liveGraph`; the version export stores the same graph below.
// Authorship is not exported either: the preview leaves it unknown (null).
const authorshipFields = Object.keys(LIVE_AUTHORSHIP);

/** What the export does to a row whose shape is otherwise identical: drop DB columns and authorship, tag the type. */
function exported<T extends object>(nodeType: SnapshotNodeType, row: T): SnapshotNode {
    const copy: Record<string, unknown> = { ...row, node_type: nodeType };
    for (const field of ['graph', 'created_at', 'updated_at', ...authorshipFields]) delete copy[field];
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
        exported('KeyValueNode', { ...liveKeyValue, key_value_table_name: 'Customers' }),
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

/** Canvas ids are random; replace each by its order of first appearance. DB columns and authorship are not exported. */
function comparable(flow: FlowModel): unknown {
    const uuidPattern = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/g;
    const order = new Map<string, number>();
    const json = JSON.stringify(flow, (key, value: unknown) =>
        ['graph', 'created_at', 'updated_at', ...authorshipFields].includes(key) ? undefined : value
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

    it('leaves every node unattributed, since the export carries no authorship', () => {
        const graphDto = mapSnapshotToGraphDto(snapshot, secretsByName);

        for (const node of snapshot.nodes) {
            const [item] = graphDto[SNAPSHOT_NODE_LIST_KEY[node.node_type]] as object[];
            expect(item).toMatchObject({ created_by: null, last_edited_by: null, last_edited_at: null });
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
        expect((byId(ID.webhook).data as { webhook_trigger: unknown }).webhook_trigger).toBe(LIVE_WEBHOOK_TRIGGER_ID);
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

describe('buildPreviewFlowModel (key-value nodes)', () => {
    it('shows a node whose table is gone with no table selected', () => {
        const orphaned: GraphVersionSnapshot = {
            // The backend found no table to re-bind the stored name to.
            nodes: [exported('KeyValueNode', { ...liveKeyValue, key_value_table: null, key_value_table_name: 'Gone' })],
        };
        const { flow } = buildPreviewFlowModel(orphaned, secretsByName, availableFlows);

        const keyValue = flow.nodes.find((node) => node.type === NodeType.KEY_VALUE) as KeyValueNodeModel;
        expect(keyValue.data).toEqual({ key_value_table: null, mode: 'write', entries: liveKeyValue.entries });
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
