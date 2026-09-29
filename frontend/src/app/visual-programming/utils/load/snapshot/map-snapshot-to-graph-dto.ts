import { GetGraphLightRequest, GraphDto } from '../../../../features/flows/models/graph.model';
import {
    GraphVersionSnapshot,
    SnapshotNode,
    SnapshotNodeType,
    SnapshotSecretDeclarations,
} from '../../../../features/flows/models/graph-version-preview.model';
import { FlowModel } from '../../../core/models/flow.model';
import { buildFlowModelFromGraphDto } from '../build-flow-model-from-graph-dto';
import {
    buildScheduleBlock,
    resolveDeclaredSecrets,
    resolveSecretIdByName,
    toLiveClassificationPythonCode,
    toLiveInlineSurface,
    toLivePythonCode,
    toLiveSearchConfigs,
} from './snapshot-field-adapters';

/** Every GraphDto key that holds a list of nodes. */
type GraphDtoNodeListKey = Extract<keyof GraphDto, `${string}_node_list` | 'graph_note_list'>;

/**
 * Which GraphDto list each exported node type belongs to. `satisfies` makes a snapshot type
 * without a list a build error; `UnmappedGraphDtoNodeList` below does the same for a list
 * without a snapshot type.
 */
export const SNAPSHOT_NODE_LIST_KEY = {
    StartNode: 'start_node_list',
    EndNode: 'end_node_list',
    GraphNote: 'graph_note_list',
    PythonNode: 'python_node_list',
    TaskNode: 'task_node_list',
    AgentNode: 'agent_node_list',
    FileExtractorNode: 'file_extractor_node_list',
    AudioTranscriptionNode: 'audio_transcription_node_list',
    SubgraphNode: 'subgraph_node_list',
    WebhookTriggerNode: 'webhook_trigger_node_list',
    TelegramTriggerNode: 'telegram_trigger_node_list',
    ScheduleTriggerNode: 'schedule_trigger_node_list',
    DecisionTableNode: 'decision_table_node_list',
    ClassificationDecisionTableNode: 'classification_decision_table_node_list',
    KnowledgeNode: 'knowledge_node_list',
} as const satisfies Record<SnapshotNodeType, GraphDtoNodeListKey>;

type AssertNever<T extends never> = T;
/**
 * Must stay `never`: a GraphDto node list that no snapshot type fills. `llm_node_list` is a
 * frontend-only leftover — no backend model or export produces it.
 */
export type UnmappedGraphDtoNodeList = AssertNever<
    Exclude<GraphDtoNodeListKey, (typeof SNAPSHOT_NODE_LIST_KEY)[SnapshotNodeType] | 'llm_node_list'>
>;

type SnapshotNodeOfType<TNodeType extends SnapshotNodeType> = Extract<SnapshotNode, { node_type: TNodeType }>;
type NodeListItem<TKey extends GraphDtoNodeListKey> = NonNullable<GraphDto[TKey]>[number];

interface AdapterContext {
    secretsByName: ReadonlyMap<string, number>;
    secretDeclarations: SnapshotSecretDeclarations | undefined;
}

type SnapshotNodeAdapters = {
    [TNodeType in SnapshotNodeType]: (
        node: SnapshotNodeOfType<TNodeType>,
        context: AdapterContext
    ) => NodeListItem<(typeof SNAPSHOT_NODE_LIST_KEY)[TNodeType]>;
};

/**
 * The export omits `graph`, `created_at` and `updated_at`; the load mappers never read them.
 * Foreign keys the backend nulled for a missing dependency (subgraph, webhook trigger, agent
 * definition, LLM config, …) are passed through as null — the node is kept.
 */
const NOT_PERSISTED = { graph: 0, created_at: '', updated_at: '' } as const;

const SNAPSHOT_NODE_ADAPTERS: SnapshotNodeAdapters = {
    StartNode: (node) => ({ ...node, graph: 0 }),
    EndNode: (node) => ({ ...node, graph: 0 }),
    GraphNote: (node) => ({ ...node, graph: 0 }),
    PythonNode: (node, context) => ({
        ...node,
        graph: 0,
        python_code: toLivePythonCode(node.python_code, declaredSecrets(node.id, 'python_code', context)),
    }),
    TaskNode: (node) => ({
        ...node,
        ...NOT_PERSISTED,
        inline_surface: toLiveInlineSurface(node.inline_surface),
    }),
    AgentNode: (node) => ({
        ...node,
        graph: 0,
        inline_surface: toLiveInlineSurface(node.inline_surface),
    }),
    FileExtractorNode: (node) => ({ ...node, graph: 0 }),
    AudioTranscriptionNode: (node) => ({ ...node, graph: 0 }),
    SubgraphNode: (node) => ({ ...node, graph: 0 }),
    WebhookTriggerNode: (node, context) => ({
        ...node,
        graph: 0,
        webhook_trigger_path: '',
        webhook_trigger: node.webhook_trigger,
        python_code: toLivePythonCode(node.python_code, declaredSecrets(node.id, 'python_code', context)),
    }),
    TelegramTriggerNode: (node, context) => ({
        ...node,
        graph: 0,
        webhook_trigger: node.webhook_trigger,
        telegram_bot_api_key_secret_id: resolveSecretIdByName(
            context.secretDeclarations?.telegram?.[String(node.id)],
            context.secretsByName
        ),
    }),
    ScheduleTriggerNode: (node) => ({
        id: node.id,
        node_name: node.node_name,
        metadata: node.metadata,
        is_active: node.is_active,
        current_runs: node.current_runs ?? 0,
        content_hash: '',
        schedule: buildScheduleBlock(node),
        ...NOT_PERSISTED,
    }),
    DecisionTableNode: (node) => ({ ...node, graph: 0 }),
    ClassificationDecisionTableNode: (node, context) => ({
        ...node,
        graph: 0,
        pre_python_code: toLiveClassificationPythonCode(
            node.pre_python_code,
            declaredSecrets(node.id, 'pre_python_code', context)
        ),
        post_python_code: toLiveClassificationPythonCode(
            node.post_python_code,
            declaredSecrets(node.id, 'post_python_code', context)
        ),
    }),
    KnowledgeNode: (node) => ({
        id: node.id,
        node_name: node.node_name,
        metadata: node.metadata,
        input_map: node.input_map ?? {},
        output_variable_path: node.output_variable_path,
        source_collection: node.source_collection,
        query: node.query,
        search_method: node.search_method,
        rag_type: node.rag_type,
        rag_id: node.rag_id,
        search_configs: toLiveSearchConfigs(node),
        content_hash: null,
        ...NOT_PERSISTED,
    }),
};

/**
 * Turns a stored version snapshot (export format) into the live GraphDto shape, so the preview
 * goes through exactly the same loaders as the live canvas. Pure: `secretsByName` (the
 * organisation's current secrets) is passed in. Node types this build does not know are skipped.
 */
export function mapSnapshotToGraphDto(
    snapshot: GraphVersionSnapshot,
    secretsByName: ReadonlyMap<string, number>
): GraphDto {
    const context: AdapterContext = { secretsByName, secretDeclarations: snapshot.secret_declarations };
    const nodeLists = emptyNodeLists();

    for (const node of snapshot.nodes ?? []) {
        if (!Object.hasOwn(SNAPSHOT_NODE_ADAPTERS, node.node_type)) continue;
        (nodeLists[SNAPSHOT_NODE_LIST_KEY[node.node_type]] as unknown[]).push(adaptNode(node, context));
    }

    return {
        id: 0,
        uuid: '',
        name: '',
        description: '',
        save_version: 0,
        metadata: (snapshot.metadata ?? {}) as unknown as FlowModel,
        ...nodeLists,
        edge_list: (snapshot.edge_list ?? []).map((edge) => ({ ...edge, graph: 0 })),
        conditional_edge_list: (snapshot.conditional_edge_list ?? []).map((edge) => ({
            ...edge,
            graph: 0,
            python_code: toLivePythonCode(
                edge.python_code,
                resolveDeclaredSecrets(
                    snapshot.secret_declarations?.conditional_edges?.find(
                        (declaration) => declaration.source_node_id === edge.source_node_id
                    )?.names,
                    secretsByName
                )
            ),
        })),
    };
}

/**
 * The canvas model for a version preview: snapshot → GraphDto → the live post-load pipeline, then
 * every node is detached from the backend (`backendId: null`) so no panel fetches or polls live
 * data. `snapshotIdToNodeUuid` maps snapshot node ids to canvas node ids (for warnings that point
 * at a node).
 */
export function buildPreviewFlowModel(
    snapshot: GraphVersionSnapshot,
    secretsByName: ReadonlyMap<string, number>,
    availableFlows: readonly Pick<GetGraphLightRequest, 'id'>[]
): { flow: FlowModel; snapshotIdToNodeUuid: Map<number, string> } {
    const loadedFlow = buildFlowModelFromGraphDto(mapSnapshotToGraphDto(snapshot, secretsByName), availableFlows);

    const snapshotIdToNodeUuid = new Map<number, string>();
    for (const node of loadedFlow.nodes) {
        if (node.backendId !== null) snapshotIdToNodeUuid.set(node.backendId, node.id);
    }

    return {
        flow: { ...loadedFlow, nodes: loadedFlow.nodes.map((node) => ({ ...node, backendId: null })) },
        snapshotIdToNodeUuid,
    };
}

function adaptNode(node: SnapshotNode, context: AdapterContext): unknown {
    const adapter = SNAPSHOT_NODE_ADAPTERS[node.node_type] as (node: SnapshotNode, context: AdapterContext) => unknown;
    return adapter(node, context);
}

function emptyNodeLists(): { [TKey in GraphDtoNodeListKey]-?: NonNullable<GraphDto[TKey]> } {
    return {
        start_node_list: [],
        end_node_list: [],
        graph_note_list: [],
        python_node_list: [],
        task_node_list: [],
        agent_node_list: [],
        llm_node_list: [],
        file_extractor_node_list: [],
        audio_transcription_node_list: [],
        subgraph_node_list: [],
        webhook_trigger_node_list: [],
        telegram_trigger_node_list: [],
        schedule_trigger_node_list: [],
        decision_table_node_list: [],
        classification_decision_table_node_list: [],
        knowledge_node_list: [],
    };
}

function declaredSecrets(nodeId: number, codeField: string, context: AdapterContext) {
    return resolveDeclaredSecrets(
        context.secretDeclarations?.nodes?.[String(nodeId)]?.[codeField],
        context.secretsByName
    );
}
