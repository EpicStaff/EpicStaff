import { GraphDto } from '../../../features/flows/models/graph.model';
import { FlowModel } from '../../core/models/flow.model';
import { GetKnowledgeRetrieverNodeRequest } from '../../core/models/knowledge-retriever-node.model';
import { KnowledgeRetrieverNodeModel } from '../../core/models/node.model';
import { mapKnowledgeRetrieverNodeToModel } from '../load/nodes/knowledge-retriever-node.mapper';
import { getNodeDiff } from './diff';
import { patchFlowStateWithBackendIds } from './patch';
import { buildBulkSavePayload } from './payload';

const dto: GetKnowledgeRetrieverNodeRequest = {
    id: 0,
    graph: 1,
    source_collection: 5,
    search_configs: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    metadata: {},
    node_name: 'Knowledge Retriever #1',
    node_number: null,
    input_map: {},
    output_variable_path: 'variables.context',
    query: 'what is {variables.topic}',
    search_method: null,
    rag_type: 'naive',
    rag_id: 7,
    content_hash: null,
    created_by: null,
    last_edited_by: null,
    last_edited_at: null,
};

const emptyConnectionDiff = { toCreate: [], toDelete: [], toUpdate: [] };

describe('knowledge-retriever node save', () => {
    it('patches the new backendId so the next save updates the node in place', () => {
        const created: KnowledgeRetrieverNodeModel = { ...mapKnowledgeRetrieverNodeToModel(dto), backendId: null };
        const empty = { nodes: [], connections: [] } as unknown as FlowModel;
        const firstSaved = { nodes: [created], connections: [] } as unknown as FlowModel;
        const firstDiff = getNodeDiff(empty, firstSaved);

        const responseGraph = { knowledge_node_list: [{ ...dto, id: 40 }] } as unknown as GraphDto;
        const patched = patchFlowStateWithBackendIds(firstSaved, empty, firstDiff, responseGraph);

        expect(patched.nodes[0].backendId).toBe(40);

        const edited: KnowledgeRetrieverNodeModel = {
            ...(patched.nodes[0] as KnowledgeRetrieverNodeModel),
            output_variable_path: 'variables.changed',
        };
        const secondSaved = { ...patched, nodes: [edited] } as FlowModel;
        const secondDiff = getNodeDiff(patched, secondSaved);
        const payload = buildBulkSavePayload(1, secondDiff, emptyConnectionDiff, secondSaved, new Map(), 1);

        expect(secondDiff.knowledgeRetrieverNodes.toCreate).toEqual([]);
        expect(secondDiff.knowledgeRetrieverNodes.toDelete).toEqual([]);
        expect(payload['knowledge_node_list']).toEqual([expect.objectContaining({ id: 40 })]);
        expect((payload['deleted'] as Record<string, unknown> | undefined)?.['knowledge_node_ids'] ?? []).toEqual([]);
    });
});
