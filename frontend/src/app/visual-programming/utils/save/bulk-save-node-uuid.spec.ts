import { GraphDto } from '../../../features/flows/models/graph.model';
import { FlowModel } from '../../core/models/flow.model';
import { NodeModel } from '../../core/models/node.model';
import { buildFlowModelFromGraphDto } from '../load/build-flow-model-from-graph-dto';
import { liveGraph } from '../testing/live-graph.fixture';
import { buildUuidToBackendIdMap, getConnectionDiff, getNodeDiff } from './diff';
import { buildBulkSavePayload } from './payload';

const graph: GraphDto = { ...liveGraph };
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

/** Every node item in the payload, keyed by its list. */
function payloadNodeItems(payload: Record<string, unknown>): [string, Record<string, unknown>][] {
    return Object.entries(payload)
        .filter(([key]) => key.endsWith('_list') && key !== 'edge_list')
        .flatMap(([key, items]) =>
            (items as Record<string, unknown>[]).map((item): [string, Record<string, unknown>] => [key, item])
        );
}

function withNodes(flow: FlowModel, mapNode: (node: NodeModel) => NodeModel): FlowModel {
    return { ...flow, nodes: flow.nodes.map(mapNode) };
}

const movedFlow = withNodes(loadedFlow, (node) => ({
    ...node,
    position: { x: node.position.x + 10, y: node.position.y },
}));
const otherUuidFlow = withNodes(loadedFlow, (node) => ({ ...node, nodeUuid: `${node.nodeUuid}-other` }));

describe('node uuid in the bulk-save payload', () => {
    it('sends the canvas uuid of every created node, so the backend stores the same one', () => {
        const items = payloadNodeItems(bulkSavePayload(emptyFlow, loadedFlow));
        const nodeById = new Map(loadedFlow.nodes.map((node) => [node.id, node]));

        expect(items).toHaveLength(loadedFlow.nodes.length);
        for (const [, item] of items) {
            const node = nodeById.get(item['temp_id'] as string)!;
            expect(node.nodeUuid).toEqual(expect.any(String));
            expect(item['uuid']).toBe(node.nodeUuid);
        }
    });

    it('never sends the uuid of an updated node', () => {
        const items = payloadNodeItems(bulkSavePayload(loadedFlow, movedFlow));

        expect(items).toHaveLength(loadedFlow.nodes.length);
        expect(items.filter(([, item]) => 'uuid' in item)).toEqual([]);
    });

    it('targets the saved flow with every created and updated node', () => {
        const items = [
            ...payloadNodeItems(bulkSavePayload(emptyFlow, loadedFlow)),
            ...payloadNodeItems(bulkSavePayload(loadedFlow, movedFlow)),
        ];

        expect(items.filter(([, item]) => item['graph'] !== graph.id)).toEqual([]);
    });

    it('does not count a uuid change as an edit', () => {
        const changes = Object.values(getNodeDiff(loadedFlow, otherUuidFlow)).flatMap((diff) => [
            ...diff.toCreate,
            ...diff.toUpdate,
            ...diff.toDelete,
        ]);

        expect(changes).toEqual([]);
    });
});
