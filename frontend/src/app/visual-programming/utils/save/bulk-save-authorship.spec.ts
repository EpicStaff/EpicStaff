import { NodeType } from '@shared/models';

import { GraphDto } from '../../../features/flows/models/graph.model';
import { NODE_DETAILS_LIST_KEY, NODE_TYPES_WITH_DETAILS } from '../../core/helpers/node-details.util';
import { FlowModel } from '../../core/models/flow.model';
import { GetLLMNodeRequest } from '../../core/models/llm-node.model';
import { NodeModel } from '../../core/models/node.model';
import { buildFlowModelFromGraphDto } from '../load/build-flow-model-from-graph-dto';
import { LIVE_AUTHORSHIP, LIVE_WEBHOOK_TRIGGER_ID, liveGraph } from '../testing/live-graph.fixture';
import { buildUuidToBackendIdMap, getConnectionDiff, getNodeDiff } from './diff';
import { buildBulkSavePayload } from './payload';

// Authorship is read-only: the backend derives it from the request, so a save must never echo it back.
const AUTHORSHIP_KEYS = Object.keys(LIVE_AUTHORSHIP);

/** JSON paths of every authorship key anywhere in `value`. */
function authorshipPaths(value: unknown, path = '$'): string[] {
    if (Array.isArray(value)) return value.flatMap((item, index) => authorshipPaths(item, `${path}[${index}]`));
    if (value === null || typeof value !== 'object') return [];
    return Object.entries(value).flatMap(([key, child]) => [
        ...(AUTHORSHIP_KEYS.includes(key) ? [`${path}.${key}`] : []),
        ...authorshipPaths(child, `${path}.${key}`),
    ]);
}

// The shared fixture has no LLM node. Its canvas data is the nested LLM config, an authored resource itself.
const liveLlm: GetLLMNodeRequest = {
    id: 17,
    graph: 1,
    node_name: 'LLM',
    llm_config: 71,
    llm_config_detail: {
        ...LIVE_AUTHORSHIP,
        id: 71,
        custom_name: 'GPT config',
        model: 3,
        api_key_secret_id: null,
        temperature: 0.2,
        top_p: null,
        stop: null,
        max_tokens: null,
        presence_penalty: null,
        frequency_penalty: null,
        logit_bias: null,
        seed: null,
        timeout: null,
        is_visible: true,
        tags: [],
        created_at: null,
    },
    input_map: {},
    output_variable_path: null,
    metadata: {},
};

const graph: GraphDto = { ...liveGraph, llm_node_list: [liveLlm] };
const loadedFlow = buildFlowModelFromGraphDto(graph, [{ id: 99 }]);
const emptyFlow: FlowModel = { nodes: [], connections: [] };

function bulkSavePayload(previous: FlowModel, current: FlowModel): Record<string, unknown> {
    const idMap = buildUuidToBackendIdMap(current.nodes);
    return buildBulkSavePayload(
        graph.id,
        getNodeDiff(previous, current),
        getConnectionDiff(previous, current, idMap),
        current,
        idMap,
        graph.save_version
    );
}

/** Every node item in the payload, whatever its type. */
function payloadNodeItems(payload: Record<string, unknown>): Record<string, unknown>[] {
    return Object.entries(payload)
        .filter(([key]) => key.endsWith('_list') && key !== 'edge_list')
        .flatMap(([, items]) => items as Record<string, unknown>[]);
}

describe('bulk-save payload of nodes loaded from the API', () => {
    // Without this the payload checks below could pass only because the loader dropped all authorship.
    it('keeps authorship in the canvas data of LLM and knowledge nodes', () => {
        const nodeTypesKeepingAuthorship = loadedFlow.nodes
            .filter((node) => authorshipPaths(node.data).length > 0)
            .map((node) => node.type);

        expect(nodeTypesKeepingAuthorship).toEqual(
            expect.arrayContaining([NodeType.LLM, NodeType.KNOWLEDGE_RETRIEVER])
        );
    });

    it('sends no authorship when the loaded nodes are saved as new ones', () => {
        const payload = bulkSavePayload(emptyFlow, loadedFlow);

        expect(payloadNodeItems(payload)).toHaveLength(loadedFlow.nodes.length);
        expect(authorshipPaths(payload)).toEqual([]);
    });

    it('sends no authorship when every loaded node is updated', () => {
        const movedFlow: FlowModel = {
            ...loadedFlow,
            nodes: loadedFlow.nodes.map((node) => ({
                ...node,
                position: { x: node.position.x + 10, y: node.position.y },
            })),
        };

        const payload = bulkSavePayload(loadedFlow, movedFlow);

        const items = payloadNodeItems(payload);
        expect(items).toHaveLength(loadedFlow.nodes.length);
        expect(items.every((item) => item['id'] != null)).toBe(true);
        expect(authorshipPaths(payload)).toEqual([]);
    });

    it("never echoes the graph's own author, creation time or last edit", () => {
        const graphReadOnlyKeys = [...AUTHORSHIP_KEYS, 'created_at', 'updated_at'];
        // Without this the check below could pass only because the fixture graph had nothing to echo.
        expect(Object.keys(graph)).toEqual(expect.arrayContaining(graphReadOnlyKeys));

        const payload = bulkSavePayload(emptyFlow, loadedFlow);

        expect(Object.keys(payload).filter((key) => graphReadOnlyKeys.includes(key))).toEqual([]);
    });

    it('references the webhook trigger by its bare id, never as a nested trigger', () => {
        const payload = bulkSavePayload(emptyFlow, loadedFlow);

        expect(payload['webhook_trigger_node_list']).toEqual([
            expect.objectContaining({ webhook_trigger: LIVE_WEBHOOK_TRIGGER_ID }),
        ]);
        expect(payload['telegram_trigger_node_list']).toEqual([expect.objectContaining({ webhook_trigger: null })]);
    });

    it('does not count an authorship change as an edit', () => {
        const otherEditor = { id: 9, display_name: 'Grace Hopper', avatar_url: null };
        const reattributedFlow = JSON.parse(JSON.stringify(loadedFlow), (key: string, value: unknown) => {
            if (key === 'created_by') return null;
            if (key === 'last_edited_by') return otherEditor;
            if (key === 'last_edited_at') return '2026-03-04T05:06:07Z';
            return value;
        }) as FlowModel;
        expect(reattributedFlow).not.toEqual(loadedFlow);

        const changes = Object.values(getNodeDiff(loadedFlow, reattributedFlow)).flatMap((diff) => [
            ...diff.toCreate,
            ...diff.toUpdate,
            ...diff.toDelete,
        ]);

        expect(changes).toEqual([]);
    });
});

describe('bulk-save payload of nodes whose details the editor shows', () => {
    // The details dialog reads authorship from the graph response, never from the canvas, so none of it may be saved.
    const readOnlyKeys = ['authorship', 'created_at', ...AUTHORSHIP_KEYS];

    function readOnlyKeyPaths(value: unknown, path = '$'): string[] {
        if (Array.isArray(value)) return value.flatMap((item, index) => readOnlyKeyPaths(item, `${path}[${index}]`));
        if (value === null || typeof value !== 'object') return [];
        return Object.entries(value).flatMap(([key, child]) => [
            ...(readOnlyKeys.includes(key) ? [`${path}.${key}`] : []),
            ...readOnlyKeyPaths(child, `${path}.${key}`),
        ]);
    }

    function loadedNodeOf(type: NodeType): NodeModel {
        const node = loadedFlow.nodes.find((candidate) => candidate.type === type);
        if (!node) throw new Error(`The fixture graph has no ${type} node`);
        return node;
    }

    it('keeps authorship off the canvas nodes it loads', () => {
        expect(loadedFlow.nodes.filter((node) => 'authorship' in node)).toEqual([]);
    });

    it.each([...NODE_TYPES_WITH_DETAILS])('sends no authorship for a %s node, whether created or updated', (type) => {
        const loaded = loadedNodeOf(type);
        // The bulk save takes each node type under the same list key the graph response returns it in.
        const listKey = NODE_DETAILS_LIST_KEY[type as keyof typeof NODE_DETAILS_LIST_KEY];
        // Moving a node is an edit for every node type (its metadata is saved).
        const moved: FlowModel = {
            ...loadedFlow,
            nodes: loadedFlow.nodes.map((node) =>
                node.id === loaded.id ? { ...node, position: { x: node.position.x + 10, y: node.position.y } } : node
            ),
        };

        const created = bulkSavePayload(emptyFlow, loadedFlow)[listKey];
        const updated = bulkSavePayload(loadedFlow, moved)[listKey];

        expect(created).toHaveLength(1);
        expect(updated).toEqual([expect.objectContaining({ id: loaded.backendId })]);
        expect(readOnlyKeyPaths(created)).toEqual([]);
        expect(readOnlyKeyPaths(updated)).toEqual([]);
    });
});
