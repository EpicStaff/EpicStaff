import { NodeType } from '@shared/models';

import { RestoreWarning } from '../../../features/flows/models/graph.model';
import { GraphVersionSnapshot, SnapshotNode } from '../../../features/flows/models/graph-version-preview.model';
import { AgentNodeTaskUi } from '../../core/models/agent-node.model';
import { FlowModel } from '../../core/models/flow.model';
import { NodeModel } from '../../core/models/node.model';
import { buildFlowModelFromGraphDto, buildPreviewFlowModel } from '../load';
import { LIVE_NODE_ID as ID, LIVE_NODE_UUID as UUID, liveGraph } from '../testing/live-graph.fixture';
import {
    liveGraphSnapshot,
    SNAPSHOT_AVAILABLE_FLOWS,
    SNAPSHOT_SECRETS_BY_NAME,
} from '../testing/version-snapshot.fixture';
import {
    buildFlowDiff,
    buildVersionKeyValueTableNames,
    buildVersionWarningReferences,
    FieldChange,
    FlowDiff,
    NodeDiffEntry,
} from './index';

type NodeOfType<TType extends NodeType> = Extract<NodeModel, { type: TType }>;

// The version of `liveGraph`. It also declares a secret the organisation deleted since; the backend leaves
// that name out of `resolved_secrets` and warns about it (the tests that need the warning pass it).
const snapshot: GraphVersionSnapshot = liveGraphSnapshot;

/** What the backend resolves the fixture's declared secret names to: every name but the deleted one. */
const RESOLVED_SECRETS: Record<string, number> = Object.fromEntries(SNAPSHOT_SECRETS_BY_NAME);

/** A flow-to-flow comparison has no preview filtering to account for. */
const NO_VERSION_INPUTS = {
    versionWarningReferences: new Map(),
    versionKeyValueTableNames: new Map(),
} as const;

function loadLive(): FlowModel {
    return buildFlowModelFromGraphDto(liveGraph, SNAPSHOT_AVAILABLE_FLOWS);
}

/**
 * The diff the preview will build from its response (snapshot, warnings, `resolved_secrets`), against the
 * live canvas.
 */
function diffVersion(
    version: GraphVersionSnapshot,
    options: { warnings?: RestoreWarning[]; liveFlow?: FlowModel } = {}
): FlowDiff {
    const secretsByName = new Map(Object.entries(RESOLVED_SECRETS));
    const { flow, snapshotIdToCanvasId } = buildPreviewFlowModel(version, secretsByName, SNAPSHOT_AVAILABLE_FLOWS);
    return buildFlowDiff({
        versionFlow: flow,
        liveFlow: options.liveFlow ?? loadLive(),
        versionWarningReferences: buildVersionWarningReferences(options.warnings ?? [], snapshotIdToCanvasId),
        versionKeyValueTableNames: buildVersionKeyValueTableNames(version.nodes, snapshotIdToCanvasId),
    });
}

function withSnapshotNode(
    version: GraphVersionSnapshot,
    snapshotId: number,
    patch: Record<string, unknown>
): GraphVersionSnapshot {
    return {
        ...version,
        nodes: version.nodes.map((node) => (node.id === snapshotId ? ({ ...node, ...patch } as SnapshotNode) : node)),
    };
}

function withCodeSecrets(version: GraphVersionSnapshot, snapshotId: number, codeFields: Record<string, string[]>) {
    return {
        ...version,
        secret_declarations: {
            ...version.secret_declarations,
            nodes: { ...version.secret_declarations?.nodes, [snapshotId]: codeFields },
        },
    };
}

function updateNode<TType extends NodeType>(
    flow: FlowModel,
    type: TType,
    update: (node: NodeOfType<TType>) => NodeOfType<TType>
): FlowModel {
    return {
        ...flow,
        nodes: flow.nodes.map((node) => (node.type === type ? update(node as NodeOfType<TType>) : node)),
    };
}

function withoutNode(flow: FlowModel, nodeUuid: string): FlowModel {
    const id = canvasIdOf(flow, nodeUuid);
    return {
        nodes: flow.nodes.filter((node) => node.id !== id),
        connections: flow.connections.filter(
            (connection) => connection.sourceNodeId !== id && connection.targetNodeId !== id
        ),
    };
}

function entryOf(diff: FlowDiff, nodeUuid: string): NodeDiffEntry {
    return diff.nodes.find((entry) => (entry.versionNode ?? entry.currentNode)?.nodeUuid === nodeUuid)!;
}

function canvasIdOf(flow: FlowModel, nodeUuid: string): string {
    return flow.nodes.find((node) => node.nodeUuid === nodeUuid)!.id;
}

/** The uuids of the nodes that have missing references. */
function nodesWithMissingReferences(diff: FlowDiff): (string | null)[] {
    return diff.nodes
        .filter((entry) => entry.missingReferences.length > 0)
        .map((entry) => (entry.versionNode ?? entry.currentNode)!.nodeUuid);
}

function warning(type: string, nodeId: number, extra: Partial<RestoreWarning> = {}): RestoreWarning {
    return { type, node_id: nodeId, node_name: 'Task', reason: 'Referenced entity no longer exists.', ...extra };
}

/** The warning the backend gives a declared secret name that no longer resolves in the organisation. */
function secretDropped(nodeId: number, field: string, missingName: string): RestoreWarning {
    return warning('secret_declaration_dropped', nodeId, { field, missing_name: missingName });
}

/** The version's decision-table groups with their routes cleared, as `filter_snapshot` leaves them. */
function clearedDecisionTableRoutes(): object[] {
    return liveGraphSnapshot.nodes
        .filter((node) => node.id === ID.decisionTable)
        .flatMap((node) => (node as { condition_groups: object[] }).condition_groups)
        .map((group) => ({ ...group, next_node_id: null }));
}

interface FieldCase {
    type: NodeType;
    nodeUuid: string;
    edit: (flow: FlowModel) => FlowModel;
    path: string;
    current: unknown;
    version: unknown;
}

function fieldCase<TType extends NodeType>(
    type: TType,
    nodeUuid: string,
    update: (node: NodeOfType<TType>) => NodeOfType<TType>,
    expected: { path: string; current: unknown; version: unknown }
): FieldCase {
    return { type, nodeUuid, edit: (flow) => updateNode(flow, type, update), ...expected };
}

const FIELD_CASES: FieldCase[] = [
    fieldCase(NodeType.START, UUID.start, (node) => ({ ...node, data: { initialState: { topic: 'news' } } }), {
        path: 'variables',
        current: { topic: 'news' },
        version: { topic: '' },
    }),
    fieldCase(NodeType.END, UUID.end, (node) => ({ ...node, data: { output_map: { answer: 'b' } } }), {
        path: 'output_map',
        current: { answer: 'b' },
        version: { answer: 'a' },
    }),
    fieldCase(NodeType.NOTE, UUID.note, (node) => ({ ...node, data: { ...node.data, content: 'bye' } }), {
        path: 'content',
        current: 'bye',
        version: 'hello',
    }),
    fieldCase(
        NodeType.PYTHON,
        UUID.python,
        (node) => ({ ...node, data: { ...node.data, code: 'def main(): return 1' } }),
        { path: 'python_code.code', current: 'def main(): return 1', version: 'def main(): pass' }
    ),
    fieldCase(NodeType.TASK, UUID.task, (node) => ({ ...node, data: { ...node.data, instructions: 'Do it well' } }), {
        path: 'instructions',
        current: 'Do it well',
        version: 'Do it',
    }),
    fieldCase(NodeType.AGENT, UUID.agent, (node) => ({ ...node, data: { ...node.data, agent_definition: 42 } }), {
        path: 'agent_definition',
        current: 42,
        version: null,
    }),
    fieldCase(NodeType.FILE_EXTRACTOR, UUID.fileExtractor, (node) => ({ ...node, node_name: 'PDFs' }), {
        path: 'node_name',
        current: 'PDFs',
        version: 'Files',
    }),
    fieldCase(NodeType.AUDIO_TO_TEXT, UUID.audio, (node) => ({ ...node, output_variable_path: 'variables.text' }), {
        path: 'output_variable_path',
        current: 'variables.text',
        version: null,
    }),
    fieldCase(NodeType.SUBGRAPH, UUID.subgraph, (node) => ({ ...node, data: { ...node.data, id: 100 } }), {
        path: 'subgraph',
        current: 100,
        version: 99,
    }),
    fieldCase(
        NodeType.WEBHOOK_TRIGGER,
        UUID.webhook,
        (node) => ({ ...node, data: { ...node.data, use_storage: true } }),
        { path: 'use_storage', current: true, version: false }
    ),
    fieldCase(
        NodeType.TELEGRAM_TRIGGER,
        UUID.telegram,
        (node) => ({ ...node, data: { ...node.data, webhook_trigger: 5 } }),
        { path: 'webhook_trigger', current: 5, version: null }
    ),
    fieldCase(
        NodeType.SCHEDULE_TRIGGER,
        UUID.schedule,
        (node) => ({ ...node, data: { ...node.data, intervalEvery: 2 } }),
        { path: 'interval_every', current: 2, version: 1 }
    ),
    fieldCase(
        NodeType.TABLE,
        UUID.decisionTable,
        (node) => ({
            ...node,
            data: {
                ...node.data,
                table: {
                    ...node.data.table,
                    condition_groups: node.data.table.condition_groups.map((group) => ({
                        ...group,
                        expression: 'x > 1',
                    })),
                },
            },
        }),
        { path: 'condition_groups[name=yes].expression', current: 'x > 1', version: null }
    ),
    fieldCase(
        NodeType.CLASSIFICATION_TABLE,
        UUID.classificationTable,
        (node) => ({ ...node, data: { ...node.data, table: { ...node.data.table, default_llm_config: 3 } } }),
        { path: 'default_llm_config', current: 3, version: null }
    ),
    fieldCase(
        NodeType.KNOWLEDGE_RETRIEVER,
        UUID.knowledge,
        (node) => ({ ...node, data: { ...node.data, query: 'r' } }),
        { path: 'query', current: 'r', version: 'q' }
    ),
    fieldCase(NodeType.KEY_VALUE, UUID.keyValue, (node) => ({ ...node, data: { ...node.data, mode: 'read' } }), {
        path: 'mode',
        current: 'read',
        version: 'write',
    }),
];

describe('buildFlowDiff', () => {
    it('covers every node type of the fixture with a field case', () => {
        expect(new Set(FIELD_CASES.map((testCase) => testCase.type))).toEqual(
            new Set(loadLive().nodes.map((node) => node.type))
        );
    });

    it.each(FIELD_CASES.map((testCase) => [testCase.type, testCase] as const))(
        '%s: a changed field gives its path, the current value and the version value a restore writes',
        (_type, testCase) => {
            const diff = diffVersion(snapshot, { liveFlow: testCase.edit(loadLive()) });

            const entry = entryOf(diff, testCase.nodeUuid);
            expect(entry.status).toBe('changed');
            expect(entry.fields).toEqual([
                expect.objectContaining({
                    path: testCase.path,
                    status: 'changed',
                    current: testCase.current,
                    version: testCase.version,
                }),
            ]);
            expect(diff.summary).toMatchObject({ added: 0, deleted: 0, changed: 1 });
        }
    );

    it.each([
        fieldCase(
            NodeType.PYTHON,
            UUID.python,
            (node) => ({ ...node, data: { ...node.data, execution_timeout: 90 } }),
            { path: 'python_code.execution_timeout', current: 90, version: null }
        ),
        fieldCase(
            NodeType.WEBHOOK_TRIGGER,
            UUID.webhook,
            (node) => ({
                ...node,
                data: { ...node.data, python_code: { ...node.data.python_code, execution_timeout: 90 } },
            }),
            { path: 'python_code.execution_timeout', current: 90, version: null }
        ),
        fieldCase(
            NodeType.CLASSIFICATION_TABLE,
            UUID.classificationTable,
            (node) => ({
                ...node,
                data: {
                    ...node.data,
                    table: {
                        ...node.data.table,
                        post_computation: { ...node.data.table.post_computation!, execution_timeout: 90 },
                    },
                },
            }),
            { path: 'post_computation.execution_timeout', current: 90, version: null }
        ),
    ])('$type: a changed execution timeout is a change', (testCase) => {
        const diff = diffVersion(snapshot, { liveFlow: testCase.edit(loadLive()) });

        expect(entryOf(diff, testCase.nodeUuid).fields).toEqual([
            expect.objectContaining({ path: testCase.path, current: testCase.current, version: testCase.version }),
        ]);
    });

    // The fixture's Python node is a version saved before venvs: it has libraries and no venv, which reads as no venv.
    it.each([
        {
            canvasVenv: 5,
            fields: [expect.objectContaining({ path: 'python_code.venv_id', current: 5, version: null })],
        },
        { canvasVenv: null, fields: [] },
    ])('compares the venv of a Python node: canvas venv $canvasVenv', ({ canvasVenv, fields }) => {
        const liveFlow = updateNode(loadLive(), NodeType.PYTHON, (node) => ({
            ...node,
            data: { ...node.data, venv_id: canvasVenv },
        }));

        expect(entryOf(diffVersion(snapshot, { liveFlow }), UUID.python).fields).toEqual(fields);
    });

    it('shows what a restore does: version-only nodes and edges are added, canvas-only ones deleted', () => {
        // The version has a node and an edge the canvas lacks; the canvas has the note and an edge the version lacks.
        const withoutNote = withoutNode(loadLive(), UUID.note);
        const extractor = withoutNote.nodes.find((node) => node.type === NodeType.FILE_EXTRACTOR)!;
        const versionFlow: FlowModel = {
            nodes: [...withoutNote.nodes, { ...extractor, id: 'version-only', nodeUuid: 'version-only-uuid' }],
            connections: [
                ...withoutNote.connections,
                {
                    ...withoutNote.connections[0],
                    id: 'version-edge',
                    sourceNodeId: canvasIdOf(withoutNote, UUID.python),
                    targetNodeId: 'version-only',
                },
            ],
        };
        const live = loadLive();
        const liveFlow: FlowModel = {
            ...live,
            connections: [
                ...live.connections,
                {
                    ...live.connections[0],
                    id: 'canvas-edge',
                    sourceNodeId: canvasIdOf(live, UUID.python),
                    targetNodeId: canvasIdOf(live, UUID.audio),
                },
            ],
        };

        const diff = buildFlowDiff({ versionFlow, liveFlow, ...NO_VERSION_INPUTS });

        const added = entryOf(diff, 'version-only-uuid');
        expect([added.status, added.versionNode?.id, added.currentNode]).toEqual(['added', 'version-only', undefined]);
        const deleted = entryOf(diff, UUID.note);
        expect([deleted.status, deleted.versionNode, deleted.currentNode?.nodeUuid]).toEqual([
            'deleted',
            undefined,
            UUID.note,
        ]);
        expect(
            diff.edges
                .filter((edge) => edge.status !== 'unchanged')
                .map((edge) => [edge.status, edge.sourceKey, edge.targetKey])
        ).toEqual([
            ['added', `uuid:${UUID.python}`, added.key],
            ['deleted', `uuid:${UUID.python}`, `uuid:${UUID.audio}`],
        ]);
        expect(diff.summary).toMatchObject({ added: 1, deleted: 1, changed: 0, edgesAdded: 1, edgesDeleted: 1 });
    });

    it('finds no change after a restore: same uuids, new canvas ids, no backend ids, renumbered names', () => {
        const renumbered: GraphVersionSnapshot = {
            ...snapshot,
            nodes: snapshot.nodes.map((node) => ({ ...node, node_name: `${node.node_name} #${node.id + 20}` })),
        };
        const liveFlow = loadLive();

        const diff = diffVersion(renumbered, { liveFlow });

        const versionIds = diff.nodes.map((entry) => entry.versionNode!.id);
        expect(versionIds.some((id) => liveFlow.nodes.some((node) => node.id === id))).toBe(false);
        expect(diff.nodes.every((entry) => entry.versionNode!.backendId === null)).toBe(true);
        expect(diff.nodes.every((entry) => entry.status === 'unchanged' && entry.fields.length === 0)).toBe(true);
        expect(nodesWithMissingReferences(diff)).toEqual([]);
        expect(diff.summary).toEqual({
            added: 0,
            deleted: 0,
            changed: 0,
            unchanged: 16,
            edgesAdded: 0,
            edgesDeleted: 0,
        });
        // 3 plain edges, 2 decision-table routes, 2 classification-table routes.
        expect(diff.edges).toHaveLength(7);
        expect(diff.matchRate).toBe(1);
    });

    it('ignores layout: position, size, colour, icon, #N badge, ports, note background and edge waypoints', () => {
        const live = loadLive();
        const moved: FlowModel = {
            nodes: live.nodes.map((node) => ({
                ...node,
                position: { x: node.position.x + 50, y: 7 },
                size: { width: 1, height: 2 },
                color: '#000000',
                icon: 'ti ti-x',
                nodeNumber: (node.nodeNumber ?? 0) + 10,
                ports: [],
                isBlocked: !node.isBlocked,
            })),
            connections: live.connections.map((connection) => ({
                ...connection,
                id: `${connection.id}-regenerated`,
                waypoints: [{ x: 1, y: 2 }],
                userAdjustedWaypoints: true,
            })),
        };
        const recoloured = updateNode(moved, NodeType.NOTE, (node) => ({
            ...node,
            data: { ...node.data, backgroundColor: '#123456' },
        }));

        const diff = buildFlowDiff({ versionFlow: live, liveFlow: recoloured, ...NO_VERSION_INPUTS });

        expect(diff.nodes.every((entry) => entry.status === 'unchanged')).toBe(true);
        expect(diff.edges.every((edge) => edge.status === 'unchanged')).toBe(true);
    });

    it('compares secrets as a set of names', () => {
        const withSecretNames = (names: string[]) =>
            updateNode(loadLive(), NodeType.PYTHON, (node) => ({
                ...node,
                data: { ...node.data, secret_names: names },
            }));

        const diff = buildFlowDiff({
            versionFlow: withSecretNames(['API_KEY', 'OTHER']),
            liveFlow: withSecretNames(['OTHER', 'API_KEY']),
            ...NO_VERSION_INPUTS,
        });

        expect(entryOf(diff, UUID.python).status).toBe('unchanged');
    });

    it('compares the resolved secret names: a secret the canvas has and the version does not is removed', () => {
        const liveFlow = updateNode(loadLive(), NodeType.PYTHON, (node) => ({
            ...node,
            data: { ...node.data, secret_ids: [101, 102], secret_names: ['API_KEY', 'BOT_KEY'] },
        }));

        expect(entryOf(diffVersion(snapshot, { liveFlow }), UUID.python).fields).toEqual([
            {
                path: 'python_code.secret_names',
                field: 'python_code.secret_names',
                status: 'changed',
                current: ['API_KEY', 'BOT_KEY'],
                version: ['API_KEY'],
            },
        ]);
    });

    it.each([
        [
            'Python code',
            ID.python,
            UUID.python,
            { python_code: ['API_KEY', 'GONE'] },
            'python_code',
            'python_code.secret_names',
        ],
        [
            'webhook code',
            ID.webhook,
            UUID.webhook,
            { python_code: ['GONE'] },
            'python_code',
            'python_code.secret_names',
        ],
        [
            'classification pre-computation',
            ID.classificationTable,
            UUID.classificationTable,
            { pre_python_code: ['API_KEY', 'GONE'] },
            'pre_python_code',
            'pre_computation.secret_names',
        ],
        [
            'classification post-computation',
            ID.classificationTable,
            UUID.classificationTable,
            { pre_python_code: ['API_KEY'], post_python_code: ['GONE'] },
            'post_python_code',
            'post_computation.secret_names',
        ],
    ])(
        '%s: a declared secret the organisation deleted is a missing reference from its warning, not a change',
        (_case, snapshotId, nodeUuid, codeFields, backendField, path) => {
            const version = withCodeSecrets(snapshot, snapshotId, codeFields);
            const warnings = [secretDropped(snapshotId, backendField, 'GONE')];

            const entry = entryOf(diffVersion(version, { warnings }), nodeUuid);

            expect(entry.status).toBe('unchanged');
            expect(entry.fields).toEqual([]);
            expect(entry.missingReferences).toEqual([{ path, field: path, missing: 'GONE', source: 'warning' }]);
        }
    );

    it('reports a Telegram bot key that no longer resolves as a missing reference, and the key a restore clears', () => {
        const version: GraphVersionSnapshot = {
            ...snapshot,
            secret_declarations: { ...snapshot.secret_declarations, telegram: { [ID.telegram]: 'GONE_KEY' } },
        };
        const warnings = [secretDropped(ID.telegram, 'telegram_bot_api_key_secret', 'GONE_KEY')];

        const entry = entryOf(diffVersion(version, { warnings }), UUID.telegram);

        expect(entry.status).toBe('changed');
        expect(entry.fields).toEqual([
            expect.objectContaining({ path: 'telegram_bot_api_key_secret_id', current: 102, version: null }),
        ]);
        expect(entry.missingReferences).toEqual([
            {
                path: 'telegram_bot_api_key_secret_id',
                field: 'telegram_bot_api_key_secret_id',
                missing: 'GONE_KEY',
                source: 'warning',
            },
        ]);
    });

    it('gives only the warned secret a missing reference; the names the backend resolved give no change', () => {
        const warnings = [secretDropped(ID.python, 'python_code', 'DELETED_SECRET')];

        const diff = diffVersion(liveGraphSnapshot, { warnings });

        expect(diff.summary.changed).toBe(0);
        expect(nodesWithMissingReferences(diff)).toEqual([UUID.python]);
        expect(entryOf(diff, UUID.python).missingReferences).toEqual([
            {
                path: 'python_code.secret_names',
                field: 'python_code.secret_names',
                missing: 'DELETED_SECRET',
                source: 'warning',
            },
        ]);
    });

    it('reports a Key-Value table the preview could not re-bind by its stored name as a missing reference', () => {
        const version = withSnapshotNode(snapshot, ID.keyValue, { key_value_table: null });

        const entry = entryOf(diffVersion(version), UUID.keyValue);

        expect(entry.fields).toEqual([
            expect.objectContaining({ path: 'key_value_table', current: 61, version: null }),
        ]);
        expect(entry.missingReferences).toEqual([
            { path: 'key_value_table', field: 'key_value_table', missing: 'Customers', source: 'keyValueTable' },
        ]);
    });

    it('shows a Key-Value table the version never had as a change only', () => {
        const version = withSnapshotNode(snapshot, ID.keyValue, { key_value_table: null, key_value_table_name: null });

        const entry = entryOf(diffVersion(version), UUID.keyValue);

        expect(entry.fields).toEqual([
            expect.objectContaining({ path: 'key_value_table', status: 'changed', current: 61, version: null }),
        ]);
        expect(entry.missingReferences).toEqual([]);
    });

    it('ignores test inputs and test payloads', () => {
        let liveFlow = updateNode(loadLive(), NodeType.PYTHON, (node) => ({ ...node, test_input: { topic: 'x' } }));
        liveFlow = updateNode(liveFlow, NodeType.WEBHOOK_TRIGGER, (node) => ({
            ...node,
            data: { ...node.data, test_payload: { other: true } },
        }));
        liveFlow = updateNode(liveFlow, NodeType.TELEGRAM_TRIGGER, (node) => ({
            ...node,
            data: { ...node.data, test_payload: {} },
        }));

        expect(diffVersion(snapshot, { liveFlow }).summary.changed).toBe(0);
    });

    it('reads a webhook of a version saved before the storage flag as storage off', () => {
        const oldVersion = withSnapshotNode(snapshot, ID.webhook, { use_storage: undefined });

        expect(entryOf(diffVersion(oldVersion), UUID.webhook).status).toBe('unchanged');
    });

    it.each([
        [
            'fk_nulled',
            ID.task,
            UUID.task,
            { agent_definition: null },
            { field: 'agent_definition', missing_id: 41 },
            'agent_definition',
            'agent_definition',
            41,
        ],
        [
            'surface_dropped',
            ID.task,
            UUID.task,
            { surface_list: [] },
            { missing_id: 51 },
            'surface_list',
            'surface_list',
            51,
        ],
        [
            'inline_tool_dropped',
            ID.task,
            UUID.task,
            { inline_surface: { instructions: 'Be brief', tools: { PythonCodeTool: [], MCPTool: [] } } },
            { missing_id: 21 },
            'inline_surface',
            'inline_surface',
            21,
        ],
        [
            'decision_table_ref_cleared',
            ID.decisionTable,
            UUID.decisionTable,
            { condition_groups: clearedDecisionTableRoutes() },
            { field: 'condition_groups[yes].next_node_id', missing_node_id: 404 },
            'condition_groups[name=yes].next_node',
            'condition_groups[].next_node',
            404,
        ],
    ])(
        '%s: the warning becomes a missing reference on its node, with the id the version had',
        (type, snapshotId, nodeUuid, filtered, warningFields, path, field, missing) => {
            const version = withSnapshotNode(snapshot, snapshotId, filtered);

            const diff = diffVersion(version, { warnings: [warning(type, snapshotId, warningFields)] });

            expect(nodesWithMissingReferences(diff)).toEqual([nodeUuid]);
            expect(entryOf(diff, nodeUuid).missingReferences).toEqual([{ path, field, missing, source: 'warning' }]);
        }
    );

    it.each([
        ['the canvas no longer has it either: no change, the node stays unchanged', null, 'unchanged', []],
        [
            'the canvas still has it: a restore clears it',
            41,
            'changed',
            [{ path: 'agent_definition', field: 'agent_definition', status: 'changed', current: 41, version: null }],
        ],
    ])('compares a foreign key the preview nulled normally when %s', (_case, liveAgentDefinition, status, fields) => {
        const version = withSnapshotNode(snapshot, ID.task, { agent_definition: null });
        const warnings = [warning('fk_nulled', ID.task, { field: 'agent_definition', missing_id: 41 })];
        const liveFlow = updateNode(loadLive(), NodeType.TASK, (node) => ({
            ...node,
            data: { ...node.data, agent_definition: liveAgentDefinition },
        }));

        const task = entryOf(diffVersion(version, { warnings, liveFlow }), UUID.task);

        expect(task.status).toBe(status);
        expect(task.fields).toEqual(fields);
        expect(task.missingReferences).toEqual([
            { path: 'agent_definition', field: 'agent_definition', missing: 41, source: 'warning' },
        ]);
    });

    it('gives a node in the version only its missing references too', () => {
        const liveFlow = withoutNode(loadLive(), UUID.python);
        const warnings = [secretDropped(ID.python, 'python_code', 'DELETED_SECRET')];

        const python = entryOf(diffVersion(liveGraphSnapshot, { liveFlow, warnings }), UUID.python);

        expect(python.status).toBe('added');
        expect(python.missingReferences).toEqual([
            {
                path: 'python_code.secret_names',
                field: 'python_code.secret_names',
                missing: 'DELETED_SECRET',
                source: 'warning',
            },
        ]);
    });

    it('gives a node on the canvas only no missing references', () => {
        const version = { ...snapshot, nodes: snapshot.nodes.filter((node) => node.id !== ID.python) };
        const warnings = [secretDropped(ID.python, 'python_code', 'GONE')];

        const python = entryOf(diffVersion(version, { warnings }), UUID.python);

        expect(python.status).toBe('deleted');
        expect(python.missingReferences).toEqual([]);
    });

    it('pairs a Start the editor added to the version with the canvas Start instead of adding one', () => {
        const withoutStart: GraphVersionSnapshot = {
            ...snapshot,
            nodes: snapshot.nodes.filter((node) => node.node_type !== 'StartNode'),
            edge_list: snapshot.edge_list?.filter((edge) => edge.start_node_id !== ID.start),
        };

        const diff = diffVersion(withoutStart);

        const start = diff.nodes.find((entry) => entry.type === NodeType.START)!;
        expect(start.matchedBy).toBe('start');
        expect(start.versionNode?.nodeUuid).not.toBe(UUID.start);
        expect(start.currentNode?.nodeUuid).toBe(UUID.start);
        expect(diff.nodes.filter((entry) => entry.status === 'added')).toEqual([]);
    });

    it('never matches nodes without a uuid, and reports a match rate of 0', () => {
        const withoutUuids: GraphVersionSnapshot = {
            ...snapshot,
            nodes: snapshot.nodes.map((node) => ({ ...node, uuid: undefined })),
        };

        const diff = diffVersion(withoutUuids);

        expect(diff.matchRate).toBe(0);
        expect(diff.summary).toMatchObject({ added: 15, deleted: 15 });
        expect(diff.nodes.filter((entry) => entry.matchedBy !== null).map((entry) => entry.matchedBy)).toEqual([
            'start',
        ]);
    });

    it('does not fail on a uuid repeated on the canvas: the first node matches, a restore deletes the copy', () => {
        const live = loadLive();
        const python = live.nodes.find((node) => node.type === NodeType.PYTHON)!;
        const liveFlow = { ...live, nodes: [...live.nodes, { ...python, id: 'copy-of-python' }] };

        const diff = diffVersion(snapshot, { liveFlow });

        const pythonEntries = diff.nodes.filter((entry) => entry.type === NodeType.PYTHON);
        expect(pythonEntries.map((entry) => [entry.status, entry.currentNode?.id])).toEqual([
            ['unchanged', python.id],
            ['deleted', 'copy-of-python'],
        ]);
    });

    it('shows a retargeted decision-table route as one field change, one added and one deleted edge', () => {
        const live = loadLive();
        const taskId = canvasIdOf(live, UUID.task);
        const liveFlow = updateNode(live, NodeType.TABLE, (node) => ({
            ...node,
            data: {
                ...node.data,
                table: {
                    ...node.data.table,
                    condition_groups: node.data.table.condition_groups.map((group) => ({
                        ...group,
                        next_node: taskId,
                    })),
                },
            },
        }));

        const diff = diffVersion(snapshot, { liveFlow });

        expect(entryOf(diff, UUID.decisionTable).fields).toEqual([
            {
                path: 'condition_groups[name=yes].next_node',
                field: 'condition_groups[].next_node',
                status: 'changed',
                current: `uuid:${UUID.task}`,
                version: `uuid:${UUID.end}`,
            },
        ]);
        const route = { routeKind: 'dt-route', route: 'group:yes', sourceKey: `uuid:${UUID.decisionTable}` };
        expect(diff.edges.filter((edge) => edge.status !== 'unchanged')).toEqual([
            expect.objectContaining({ ...route, status: 'added', targetKey: `uuid:${UUID.end}` }),
            expect.objectContaining({ ...route, status: 'deleted', targetKey: `uuid:${UUID.task}` }),
        ]);
    });

    it('keys classification-table routes by group name, so new port ids and route codes keep the edge', () => {
        const live = loadLive();
        const recoded = updateNode(live, NodeType.CLASSIFICATION_TABLE, (node) => ({
            ...node,
            data: {
                ...node.data,
                table: {
                    ...node.data.table,
                    condition_groups: node.data.table.condition_groups.map((group) => ({ ...group, route_code: 'B' })),
                },
            },
        }));
        const liveFlow: FlowModel = {
            ...recoded,
            connections: recoded.connections.map((connection, index) => ({
                ...connection,
                id: `regenerated-${index}`,
                sourcePortId: `${connection.sourceNodeId}_regenerated-port-${index}`,
            })),
        };

        const diff = diffVersion(snapshot, { liveFlow });

        expect(entryOf(diff, UUID.classificationTable).fields).toEqual([
            expect.objectContaining({ path: 'condition_groups[name=route].route_code', current: 'B', version: 'A' }),
        ]);
        expect(diff.edges.every((edge) => edge.status === 'unchanged')).toBe(true);
        expect(diff.edges).toContainEqual(
            expect.objectContaining({
                routeKind: 'cdt-route',
                route: 'group:route',
                sourceKey: `uuid:${UUID.classificationTable}`,
                targetKey: `uuid:${UUID.agent}`,
            })
        );
    });

    it('reports a condition group only on the canvas as one deleted item', () => {
        const liveFlow = updateNode(loadLive(), NodeType.TABLE, (node) => ({
            ...node,
            data: {
                ...node.data,
                table: {
                    ...node.data.table,
                    condition_groups: [
                        ...node.data.table.condition_groups,
                        {
                            group_name: 'no',
                            group_type: 'simple',
                            expression: null,
                            conditions: [],
                            manipulation: null,
                            next_node: null,
                            valid: true,
                            order: 2,
                        },
                    ],
                },
            },
        }));

        const fields = entryOf(diffVersion(snapshot, { liveFlow }), UUID.decisionTable).fields;

        expect(fields).toEqual([
            {
                path: 'condition_groups[name=no]',
                field: 'condition_groups[]',
                status: 'deleted',
                current: {
                    position: 2,
                    group_type: 'simple',
                    expression: null,
                    conditions: [],
                    manipulation: null,
                    next_node: null,
                },
                version: null,
            },
        ]);
    });

    it('treats group names like __proto__ and constructor as plain keys', () => {
        const renameGroups = (names: string[]) => (flow: FlowModel) =>
            updateNode(flow, NodeType.TABLE, (node) => ({
                ...node,
                data: {
                    ...node.data,
                    table: {
                        ...node.data.table,
                        condition_groups: names.map((groupName, index) => ({
                            ...node.data.table.condition_groups[0],
                            group_name: groupName,
                            order: index + 1,
                            expression: index === 0 ? null : 'x',
                        })),
                    },
                },
            }));
        const versionFlow = renameGroups(['__proto__'])(loadLive());
        const liveFlow = updateNode(renameGroups(['__proto__', 'constructor'])(loadLive()), NodeType.TABLE, (node) => ({
            ...node,
            data: {
                ...node.data,
                table: {
                    ...node.data.table,
                    condition_groups: node.data.table.condition_groups.map((group, index) =>
                        index === 0 ? { ...group, manipulation: 'y = 1' } : group
                    ),
                },
            },
        }));

        const fields = entryOf(
            buildFlowDiff({ versionFlow, liveFlow, ...NO_VERSION_INPUTS }),
            UUID.decisionTable
        ).fields;

        expect(fields.map((field) => [field.path, field.status])).toEqual([
            ['condition_groups[name=__proto__].manipulation', 'changed'],
            ['condition_groups[name=constructor]', 'deleted'],
        ]);
    });

    it('compares agent task context by task position, not by task ids that a restore renews', () => {
        const task = (overrides: Partial<AgentNodeTaskUi>): AgentNodeTaskUi => ({
            tempId: 'temp',
            name: 'Task',
            instructions: 'Go',
            output_schema: {},
            contextRefs: [],
            ...overrides,
        });
        const withTasks = (tasks: AgentNodeTaskUi[]) => (flow: FlowModel) =>
            updateNode(flow, NodeType.AGENT, (node) => ({ ...node, data: { ...node.data, tasks } }));
        const versionFlow = withTasks([
            task({ id: 1, tempId: 'a', name: 'Plan' }),
            task({ id: 2, tempId: 'b', name: 'Do', contextRefs: [{ id: 1 }] }),
        ])(loadLive());
        const restored = withTasks([
            task({ id: 11, tempId: 'x', name: 'Plan' }),
            task({ id: 12, tempId: 'y', name: 'Do', contextRefs: [{ id: 11 }] }),
        ])(loadLive());
        const edited = withTasks([
            task({ id: 11, tempId: 'x', name: 'Plan' }),
            task({ tempId: 'new', name: 'Check' }),
            task({ id: 12, tempId: 'y', name: 'Do', contextRefs: [{ tempId: 'new' }] }),
        ])(loadLive());

        expect(
            entryOf(buildFlowDiff({ versionFlow, liveFlow: restored, ...NO_VERSION_INPUTS }), UUID.agent).status
        ).toBe('unchanged');
        expect(
            entryOf(buildFlowDiff({ versionFlow, liveFlow: edited, ...NO_VERSION_INPUTS }), UUID.agent).fields.map(
                (field) => [field.path, field.status, field.current, field.version]
            )
        ).toEqual([
            ['tasks[2].name', 'changed', 'Check', 'Do'],
            ['tasks[2].context_tasks', 'changed', [], [1]],
            ['tasks[3]', 'deleted', { name: 'Do', instructions: 'Go', output_schema: {}, context_tasks: [2] }, null],
        ]);
    });

    it('mirrors: diff(a, b) is diff(b, a) with added and deleted, current and version swapped', () => {
        const before = loadLive();
        const python = canvasIdOf(before, UUID.python);
        let after = updateNode(loadLive(), NodeType.PYTHON, (node) => ({
            ...node,
            node_name: 'Renamed',
            data: { ...node.data, code: 'pass' },
        }));
        after = updateNode(after, NodeType.TABLE, (node) => ({
            ...node,
            data: { ...node.data, table: { ...node.data.table, default_next_node: canvasIdOf(after, UUID.end) } },
        }));
        const extractor = after.nodes.find((node) => node.type === NodeType.FILE_EXTRACTOR)!;
        after = {
            nodes: [
                ...after.nodes.filter((node) => node.type !== NodeType.NOTE),
                { ...extractor, id: 'new-node', nodeUuid: 'new-uuid' },
            ],
            connections: [
                ...after.connections,
                { ...after.connections[0], id: 'new-edge', sourceNodeId: canvasIdOf(after, UUID.python) },
                // Touches the canvas-only node, so its key holds a canvas id that differs between the two diffs.
                { ...after.connections[0], id: 'edge-to-new-node', targetNodeId: 'new-node' },
            ],
        };
        expect(python).not.toBe(canvasIdOf(after, UUID.python));

        const forward = buildFlowDiff({ versionFlow: before, liveFlow: after, ...NO_VERSION_INPUTS });
        const backward = buildFlowDiff({ versionFlow: after, liveFlow: before, ...NO_VERSION_INPUTS });

        const swapStatus = (status: string): string =>
            status === 'added' ? 'deleted' : status === 'deleted' ? 'added' : status;
        const nodeView = (diff: FlowDiff, swap: boolean) =>
            diff.nodes
                // Everything but `key`, which holds canvas ids of added and deleted nodes.
                .map((entry) => ({
                    uuid: (entry.versionNode ?? entry.currentNode)!.nodeUuid,
                    type: entry.type,
                    matchedBy: entry.matchedBy,
                    status: swap ? swapStatus(entry.status) : entry.status,
                    versionNode: swap ? entry.currentNode : entry.versionNode,
                    currentNode: swap ? entry.versionNode : entry.currentNode,
                    missingReferences: entry.missingReferences,
                    fields: entry.fields
                        .map((field: FieldChange) => ({
                            path: field.path,
                            field: field.field,
                            status: swap ? swapStatus(field.status) : field.status,
                            current: swap ? field.version : field.current,
                            version: swap ? field.current : field.version,
                        }))
                        .sort((left, right) => left.path.localeCompare(right.path)),
                }))
                .sort((left, right) => String(left.uuid).localeCompare(String(right.uuid)));
        // Edge keys are unique within one diff only, so edges are compared by endpoints and route.
        const edgeView = (diff: FlowDiff, swap: boolean) => {
            const uuidByKey = new Map(
                diff.nodes.map((entry) => [entry.key, (entry.versionNode ?? entry.currentNode)!.nodeUuid])
            );
            return diff.edges
                .map((edge) =>
                    [
                        swap ? swapStatus(edge.status) : edge.status,
                        edge.routeKind,
                        edge.route,
                        uuidByKey.get(edge.sourceKey),
                        uuidByKey.get(edge.targetKey),
                    ].join(' ')
                )
                .sort();
        };

        // `after` is the canvas: its new node and edges are deleted by a restore of `before`, the note added back.
        expect(forward.summary).toMatchObject({ added: 1, deleted: 1, changed: 2, edgesAdded: 1, edgesDeleted: 3 });
        expect(entryOf(forward, 'new-uuid').status).toBe('deleted');
        expect(entryOf(forward, UUID.note).status).toBe('added');
        expect(edgeView(forward, false)).toContain(`deleted edge  ${UUID.start} new-uuid`);
        expect(nodeView(backward, true)).toEqual(nodeView(forward, false));
        expect(edgeView(backward, true)).toEqual(edgeView(forward, false));
        expect(backward.summary).toEqual({
            ...forward.summary,
            added: forward.summary.deleted,
            deleted: forward.summary.added,
            edgesAdded: forward.summary.edgesDeleted,
            edgesDeleted: forward.summary.edgesAdded,
        });
    });
});
