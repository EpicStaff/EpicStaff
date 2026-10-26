import { GraphDto } from '../../../features/flows/models/graph.model';
import { FlowModel } from '../../core/models/flow.model';
import { NodeModel } from '../../core/models/node.model';
import { buildFlowModelFromGraphDto } from '../load/build-flow-model-from-graph-dto';
import { mapKnowledgeRetrieverNodeToModel } from '../load/nodes/knowledge-retriever-node.mapper';
import { mapPythonNodeToModel } from '../load/nodes/python-node.mapper';
import { LIVE_NODE_ID, liveGraph, liveKnowledge, livePython } from '../testing/live-graph.fixture';
import { buildUuidToBackendIdMap, getConnectionDiff, getNodeDiff } from './diff';
import { patchFlowStateWithBackendIds, patchLiveFlowWithBackendIds } from './patch';
import { buildBulkSavePayload } from './payload';

/**
 * Node numbers on the save path: a new node sends the number the canvas shows as a hint, and
 * takes whatever number the server gave it from the response.
 */

const emptyFlow: FlowModel = { nodes: [], connections: [] };

function flowOf(...nodes: NodeModel[]): FlowModel {
    return { nodes, connections: [] };
}

function payloadOf(previous: FlowModel, current: FlowModel): Record<string, unknown> {
    const idMap = buildUuidToBackendIdMap(current.nodes);
    return buildBulkSavePayload(
        1,
        getNodeDiff(previous, current),
        getConnectionDiff(previous, current, idMap),
        current,
        idMap,
        1
    );
}

function itemsOf(payload: Record<string, unknown>, list: string): Record<string, unknown>[] {
    return payload[list] as Record<string, unknown>[];
}

/** Every node of `liveGraph`, as the canvas would hold it before its first save. */
const unsavedLiveFlow: FlowModel = (() => {
    const loaded = buildFlowModelFromGraphDto(liveGraph, [{ id: 99 }]);
    return { ...loaded, nodes: loaded.nodes.map((node) => ({ ...node, backendId: null })) };
})();

/** The canvas node of `liveGraph` whose row is `backendId`. */
function unsavedLiveNode(backendId: number): NodeModel {
    const loaded = buildFlowModelFromGraphDto(liveGraph, [{ id: 99 }]);
    const index = loaded.nodes.findIndex((node) => node.backendId === backendId);
    return unsavedLiveFlow.nodes[index];
}

describe('node number hints in the bulk-save payload', () => {
    const payload = payloadOf(emptyFlow, unsavedLiveFlow);

    it.each([
        ['python_node_list', 1],
        ['task_node_list', 2],
        ['agent_node_list', 3],
        ['file_extractor_node_list', 4],
        ['audio_transcription_node_list', 5],
        ['subgraph_node_list', 6],
        ['webhook_trigger_node_list', 7],
        ['telegram_trigger_node_list', 8],
        ['schedule_trigger_node_list', 9],
        ['decision_table_node_list', 10],
        ['classification_decision_table_node_list', 11],
        ['knowledge_node_list', 12],
        ['key_value_node_list', 13],
    ])('sends a new %s node the number it shows as node_number_hint %i', (list, expectedHint) => {
        expect(itemsOf(payload, list).map((item) => item['node_number_hint'])).toEqual([expectedHint]);
    });

    it.each(['start_node_list', 'end_node_list', 'graph_note_list'])(
        'sends no hint for a new %s item, even when the canvas gave it a number',
        (list) => {
            // The server numbers none of these; a number on the canvas node must not reach it.
            const numberedEverywhere = {
                ...unsavedLiveFlow,
                nodes: unsavedLiveFlow.nodes.map((node) => ({ ...node, nodeNumber: 50 })),
            };

            const items = itemsOf(payloadOf(emptyFlow, numberedEverywhere), list);

            expect(items).toHaveLength(1);
            expect(items[0]).not.toHaveProperty('node_number_hint');
        }
    );

    it('keeps the number out of every node metadata it sends', () => {
        const nodeItems = Object.entries(payload)
            .filter(([key]) => key.endsWith('_list') && key !== 'edge_list')
            .flatMap(([, items]) => items as Record<string, unknown>[]);

        expect(nodeItems.length).toBe(16);
        for (const item of nodeItems) {
            expect(item['metadata']).not.toHaveProperty('nodeNumber');
        }
    });

    it('sends no hint for an updated node', () => {
        const saved = mapPythonNodeToModel(livePython);
        const renamed = { ...saved, node_name: 'Renamed' };

        const [item] = itemsOf(payloadOf(flowOf(saved), flowOf(renamed)), 'python_node_list');

        expect(item).toEqual(expect.objectContaining({ id: livePython.id, node_name: 'Renamed' }));
        expect(item).not.toHaveProperty('node_number_hint');
    });

    it('does not count a changed number as an edit of a saved node', () => {
        const saved = mapPythonNodeToModel(livePython);

        const diff = getNodeDiff(flowOf(saved), flowOf({ ...saved, nodeNumber: 9 }));

        expect(diff.pythonNodes.toUpdate).toEqual([]);
    });
});

describe('node numbers from the save response', () => {
    it.each([
        ['python', LIVE_NODE_ID.python, 1],
        ['task', LIVE_NODE_ID.task, 2],
        ['agent', LIVE_NODE_ID.agent, 3],
        ['file extractor', LIVE_NODE_ID.fileExtractor, 4],
        ['audio transcription', LIVE_NODE_ID.audio, 5],
        ['subgraph', LIVE_NODE_ID.subgraph, 6],
        ['webhook trigger', LIVE_NODE_ID.webhook, 7],
        ['telegram trigger', LIVE_NODE_ID.telegram, 8],
        ['schedule trigger', LIVE_NODE_ID.schedule, 9],
        ['decision table', LIVE_NODE_ID.decisionTable, 10],
        ['classification decision table', LIVE_NODE_ID.classificationTable, 11],
        ['knowledge retriever', LIVE_NODE_ID.knowledge, 12],
        ['key-value', LIVE_NODE_ID.keyValue, 13],
    ])(
        'gives a new %s node the number the server assigned, in both the sent and the live flow',
        (_type, backendId, serverNumber) => {
            const sent = flowOf({ ...unsavedLiveNode(backendId), nodeNumber: 100 });
            const nodeDiff = getNodeDiff(emptyFlow, sent);

            const sentPatched = patchFlowStateWithBackendIds(sent, emptyFlow, nodeDiff, liveGraph);
            const livePatched = patchLiveFlowWithBackendIds(sent, sentPatched, emptyFlow, nodeDiff, liveGraph);

            for (const patched of [sentPatched, livePatched]) {
                expect(patched.nodes[0]).toEqual(expect.objectContaining({ backendId, nodeNumber: serverNumber }));
            }
        }
    );

    it("keeps the node number when the server's number matches the hint", () => {
        const sent = flowOf({ ...mapPythonNodeToModel(livePython), id: 'new-python', backendId: null, nodeNumber: 4 });
        const response = { python_node_list: [{ ...livePython, id: 40, node_number: 4 }] } as unknown as GraphDto;

        const patched = patchFlowStateWithBackendIds(sent, emptyFlow, getNodeDiff(emptyFlow, sent), response);

        expect(patched.nodes[0]).toEqual(expect.objectContaining({ backendId: 40, nodeNumber: 4 }));
    });

    it("takes the server's number when the server assigned a different number than the hint", () => {
        const sent = flowOf({ ...mapPythonNodeToModel(livePython), id: 'new-python', backendId: null, nodeNumber: 4 });
        const response = { python_node_list: [{ ...livePython, id: 40, node_number: 6 }] } as unknown as GraphDto;

        const patched = patchFlowStateWithBackendIds(sent, emptyFlow, getNodeDiff(emptyFlow, sent), response);

        expect(patched.nodes[0]).toEqual(expect.objectContaining({ backendId: 40, nodeNumber: 6 }));
    });

    it('renumbers only the nodes this save created', () => {
        const saved = { ...mapPythonNodeToModel(livePython), nodeNumber: 2 };
        const response = { python_node_list: [livePython] } as unknown as GraphDto;

        const patched = patchFlowStateWithBackendIds(
            flowOf(saved),
            flowOf(saved),
            getNodeDiff(flowOf(saved), flowOf(saved)),
            response
        );

        expect(patched.nodes[0].nodeNumber).toBe(2);
    });
});

describe('knowledge-retriever node created by a save', () => {
    const created = { ...mapKnowledgeRetrieverNodeToModel(liveKnowledge), id: 'new-knowledge', backendId: null };
    const response = { knowledge_node_list: [liveKnowledge] } as unknown as GraphDto;
    const sent = flowOf(created);
    const nodeDiff = getNodeDiff(emptyFlow, sent);

    it('gets the backend id the server gave it', () => {
        const patched = patchFlowStateWithBackendIds(sent, emptyFlow, nodeDiff, response);

        expect(patched.nodes[0].backendId).toBe(liveKnowledge.id);
    });

    it('is not created again by the next save', () => {
        const patched = patchFlowStateWithBackendIds(sent, emptyFlow, nodeDiff, response);
        const loadedAfterSave = flowOf(mapKnowledgeRetrieverNodeToModel(liveKnowledge));

        const nextDiff = getNodeDiff(loadedAfterSave, patched);

        expect(nextDiff.knowledgeRetrieverNodes.toCreate).toEqual([]);
        expect(nextDiff.knowledgeRetrieverNodes.toDelete).toEqual([]);
    });
});
