import { NodeType } from '@shared/models';

import { GraphVersionSnapshot } from '../../../../features/flows/models/graph-version-preview.model';
import { FlowModel } from '../../../core/models/flow.model';
import { GetKnowledgeRetrieverNodeRequest } from '../../../core/models/knowledge-retriever-node.model';
import { KeyValueNodeModel, NodeModel, PythonNodeModel } from '../../../core/models/node.model';
import {
    LIVE_AUTHORSHIP,
    LIVE_NODE_ID as ID,
    LIVE_WEBHOOK_TRIGGER_ID,
    liveAgent,
    liveGraph,
    liveKeyValue,
    liveNote,
    livePython,
    liveStart,
    liveSubgraph,
    liveTask,
    liveTelegram,
    liveWebhook,
} from '../../testing/live-graph.fixture';
import {
    exported,
    liveGraphSnapshot,
    SNAPSHOT_AVAILABLE_FLOWS,
    SNAPSHOT_SECRETS_BY_NAME,
} from '../../testing/version-snapshot.fixture';
import { buildFlowModelFromGraphDto } from '../build-flow-model-from-graph-dto';
import {
    buildPreviewFlowModel,
    mapNodeAuthorshipToCanvas,
    mapSnapshotToGraphDto,
    SNAPSHOT_NODE_LIST_KEY,
    UnmappedGraphDtoNodeList,
} from './map-snapshot-to-graph-dto';
import { toLocalNaiveIso } from './snapshot-field-adapters';

const secretsByName = SNAPSHOT_SECRETS_BY_NAME;
const availableFlows = SNAPSHOT_AVAILABLE_FLOWS;
const snapshot = liveGraphSnapshot;

// The live API side of the comparison is `liveGraph`; the version export stores the same graph.
// Authorship is not exported either: the preview leaves it unknown (null).
const authorshipFields = Object.keys(LIVE_AUTHORSHIP);

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

function nodeWithSnapshotId(flow: FlowModel, snapshotIdToCanvasId: Map<number, string>, id: number): NodeModel {
    return flow.nodes.find((node) => node.id === snapshotIdToCanvasId.get(id))!;
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

    it('leaves the graph itself unattributed', () => {
        const graphDto = mapSnapshotToGraphDto(snapshot, secretsByName);

        expect(graphDto).toMatchObject({ created_by: null, last_edited_by: null, last_edited_at: null });
    });

    it('passes every node uuid through', () => {
        const graphDto = mapSnapshotToGraphDto(snapshot, secretsByName);

        for (const node of snapshot.nodes) {
            const [item] = graphDto[SNAPSHOT_NODE_LIST_KEY[node.node_type]] as { uuid: string | null }[];
            expect(node.uuid).toEqual(expect.any(String));
            expect(item.uuid).toBe(node.uuid);
        }
    });

    it('gives a node of an old version without a uuid a null one', () => {
        const withoutUuids: GraphVersionSnapshot = {
            ...snapshot,
            nodes: snapshot.nodes.map((node) => {
                const copy = { ...node };
                delete copy.uuid;
                return copy;
            }),
        };

        const graphDto = mapSnapshotToGraphDto(withoutUuids, secretsByName);

        for (const node of withoutUuids.nodes) {
            const [item] = graphDto[SNAPSHOT_NODE_LIST_KEY[node.node_type]] as { uuid: string | null }[];
            expect(item.uuid).toBeNull();
        }
    });
});

describe('buildPreviewFlowModel', () => {
    const { flow, snapshotIdToCanvasId } = buildPreviewFlowModel(snapshot, secretsByName, availableFlows);
    const byId = (id: number): NodeModel => nodeWithSnapshotId(flow, snapshotIdToCanvasId, id);

    it('equals the live loader result for the same graph (ignoring canvas ids)', () => {
        const liveFlow = buildFlowModelFromGraphDto(liveGraph, availableFlows);
        const detachedLiveFlow = { ...liveFlow, nodes: liveFlow.nodes.map((node) => ({ ...node, backendId: null })) };

        expect(comparable(flow)).toEqual(comparable(detachedLiveFlow));
    });

    it('keeps the node uuid of every node', () => {
        for (const node of snapshot.nodes) {
            expect(byId(node.id).nodeUuid).toBe(node.uuid);
        }
    });

    it('detaches every node from the backend and maps every snapshot id to a canvas node', () => {
        expect(flow.nodes.every((node) => node.backendId === null)).toBe(true);
        expect([...snapshotIdToCanvasId.keys()].sort((a, b) => a - b)).toEqual(Object.values(ID));
        expect(new Set(snapshotIdToCanvasId.values())).toEqual(new Set(flow.nodes.map((node) => node.id)));
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
        expect(table.table.default_next_node).toBe(snapshotIdToCanvasId.get(ID.task));
        expect(table.table.condition_groups[0].next_node).toBe(snapshotIdToCanvasId.get(ID.end));

        const connected = (sourceId: number, targetId: number): boolean =>
            flow.connections.some(
                (connection) =>
                    connection.sourceNodeId === snapshotIdToCanvasId.get(sourceId) &&
                    connection.targetNodeId === snapshotIdToCanvasId.get(targetId)
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

    it('keeps trigger test payloads and defaults them to {} for versions saved without one', () => {
        expect((byId(ID.webhook).data as { test_payload: unknown }).test_payload).toEqual({ id: '104' });

        const legacy: GraphVersionSnapshot = {
            nodes: [
                exported('WebhookTriggerNode', {
                    ...liveWebhook,
                    test_payload: undefined,
                    python_code: { code: 'def main(): pass', entrypoint: 'main', libraries: '' },
                }),
                exported('TelegramTriggerNode', { ...liveTelegram, test_payload: undefined }),
            ],
        };
        const { flow: legacyFlow } = buildPreviewFlowModel(legacy, secretsByName, availableFlows);

        for (const node of legacyFlow.nodes.filter((item) => item.type !== NodeType.START)) {
            expect((node.data as { test_payload: unknown }).test_payload).toEqual({});
        }
    });

    it('keeps the execution timeout of python code, and leaves it out for versions saved without one', () => {
        const timed: GraphVersionSnapshot = {
            nodes: [
                exported('PythonNode', {
                    ...livePython,
                    python_code: { code: 'def main(): pass', entrypoint: 'main', libraries: '', execution_timeout: 90 },
                }),
            ],
        };
        const pythonCodeOf = (version: GraphVersionSnapshot): PythonNodeModel['data'] =>
            (
                buildPreviewFlowModel(version, secretsByName, availableFlows).flow.nodes.find(
                    (node) => node.type === NodeType.PYTHON
                ) as PythonNodeModel
            ).data;

        expect(pythonCodeOf(timed).execution_timeout).toBe(90);
        expect((byId(ID.python) as PythonNodeModel).data.execution_timeout).toBeUndefined();
    });

    it('keeps the webhook storage flag and turns it off for versions saved without one', () => {
        const withStorage: GraphVersionSnapshot = {
            nodes: [
                exported('WebhookTriggerNode', {
                    ...liveWebhook,
                    use_storage: true,
                    python_code: { code: 'def main(): pass', entrypoint: 'main', libraries: '' },
                }),
            ],
        };
        const legacy: GraphVersionSnapshot = {
            nodes: [
                exported('WebhookTriggerNode', {
                    ...liveWebhook,
                    use_storage: undefined,
                    python_code: { code: 'def main(): pass', entrypoint: 'main', libraries: '' },
                }),
            ],
        };

        const webhookUseStorage = (version: GraphVersionSnapshot): unknown =>
            buildPreviewFlowModel(version, secretsByName, availableFlows).flow.nodes.find(
                (node) => node.type === NodeType.WEBHOOK_TRIGGER
            )?.data;

        expect(webhookUseStorage(withStorage)).toMatchObject({ use_storage: true });
        expect(webhookUseStorage(legacy)).toMatchObject({ use_storage: false });
    });
});

describe('mapNodeAuthorshipToCanvas', () => {
    const grace = { id: 9, display_name: 'Grace Hopper', avatar_url: null };
    const recorded = {
        created_by: grace,
        created_at: '2026-03-12T13:28:23Z',
        last_edited_by: null,
        last_edited_at: '2026-04-01T09:05:00Z',
    };
    const snapshotIdToCanvasId = new Map([
        [1, 'start-canvas-id'],
        [2, 'python-canvas-id'],
    ]);

    it('re-keys the recorded authorship from snapshot node ids to canvas node ids', () => {
        expect(mapNodeAuthorshipToCanvas({ '2': recorded }, snapshotIdToCanvasId)).toEqual(
            new Map([['python-canvas-id', recorded]])
        );
    });

    it('drops an entry whose node is not on the canvas', () => {
        expect(mapNodeAuthorshipToCanvas({ '3': recorded }, snapshotIdToCanvasId)).toEqual(new Map());
    });

    it('keeps only the four authorship fields', () => {
        const withExtra = { ...recorded, node_name: 'Python' } as typeof recorded;

        expect(mapNodeAuthorshipToCanvas({ '2': withExtra }, snapshotIdToCanvasId).get('python-canvas-id')).toEqual(
            recorded
        );
    });
});

describe('buildPreviewFlowModel (node numbers)', () => {
    // A version keeps the numbers its nodes had in the source graph, gaps included, and restoring
    // it keeps them too, so the preview shows the stored numbers as they are.
    const version: GraphVersionSnapshot = {
        nodes: [
            exported('StartNode', liveStart),
            exported('PythonNode', {
                ...livePython,
                node_number: 5,
                python_code: { code: 'def main(): pass', entrypoint: 'main', libraries: '' },
            }),
            exported('TaskNode', { ...liveTask, node_number: 1, inline_surface: null }),
            exported('AgentNode', { ...liveAgent, node_number: 4 }),
            exported('GraphNote', liveNote),
        ],
    };
    const numberOf = (snapshot: GraphVersionSnapshot, id: number): number | undefined => {
        const { flow, snapshotIdToCanvasId } = buildPreviewFlowModel(snapshot, secretsByName, availableFlows);
        return nodeWithSnapshotId(flow, snapshotIdToCanvasId, id).nodeNumber;
    };

    it('keeps the stored numbers #1, #4 and #5, gaps included', () => {
        expect(numberOf(version, ID.task)).toBe(1);
        expect(numberOf(version, ID.agent)).toBe(4);
        expect(numberOf(version, ID.python)).toBe(5);
    });

    it('leaves Start and Note unnumbered', () => {
        expect(numberOf(version, ID.start)).toBeUndefined();
        expect(numberOf(version, ID.note)).toBeUndefined();
    });

    it.each([1, 1_000_000])('shows the boundary number %s as stored', (stored) => {
        const boundary: GraphVersionSnapshot = {
            nodes: [exported('TaskNode', { ...liveTask, node_number: stored, inline_surface: null })],
        };

        expect(numberOf(boundary, ID.task)).toBe(stored);
    });

    it.each([0, -1, 1_000_001, 4.5, null])('does not show the unusable stored number %s as stored', (stored) => {
        const unusable: GraphVersionSnapshot = {
            nodes: [exported('TaskNode', { ...liveTask, node_number: stored, inline_surface: null })],
        };
        const [adaptedTask] = mapSnapshotToGraphDto(unusable, secretsByName).task_node_list ?? [];

        expect(adaptedTask.node_number).toBeNull();
        expect(numberOf(unusable, ID.task)).not.toBe(stored);
    });

    it('sets the counter floor to the highest usable stored number', () => {
        expect(mapSnapshotToGraphDto(version, secretsByName).node_number_seq).toBe(5);
    });

    it('ignores an unusable stored number when setting the counter floor', () => {
        const withUnusable: GraphVersionSnapshot = {
            nodes: [
                exported('TaskNode', { ...liveTask, node_number: 2, inline_surface: null }),
                exported('AgentNode', { ...liveAgent, node_number: 1_000_001 }),
            ],
        };

        expect(mapSnapshotToGraphDto(withUnusable, secretsByName).node_number_seq).toBe(2);
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
