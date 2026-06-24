import { ConnectionModel } from '../../core/models/connection.model';
import { FlowModel } from '../../core/models/flow.model';
import { NodeModel } from '../../core/models/node.model';
import { clearStaleIds } from './clear-stale-ids';

function node(id: string, backendId: number | null): NodeModel {
    return { id, backendId } as unknown as NodeModel;
}

function connection(id: string, edgeBackendId: number | null): ConnectionModel {
    return {
        id,
        sourceNodeId: 'a',
        targetNodeId: 'b',
        data: edgeBackendId == null ? null : { id: edgeBackendId },
    } as unknown as ConnectionModel;
}

describe('clearStaleIds', () => {
    it('clears backendId on a node whose backendId is not in the baseline (resurrected by undo)', () => {
        const previous: FlowModel = { nodes: [node('keep-uuid', 5)], connections: [] };
        const current: FlowModel = {
            nodes: [node('keep-uuid', 5), node('resurrected-uuid', 3)],
            connections: [],
        };

        const result = clearStaleIds(previous, current);

        const persisted = result.nodes.find((n) => n.id === 'keep-uuid');
        const orphaned = result.nodes.find((n) => n.id === 'resurrected-uuid');
        expect(persisted!.backendId).toBe(5); // untouched
        expect(orphaned!.backendId).toBeNull(); // cleared -> treated as new (temp_id)
    });

    it('clears data on a connection whose edge id is not in the baseline', () => {
        const previous: FlowModel = { nodes: [], connections: [connection('c-keep', 10)] };
        const current: FlowModel = {
            nodes: [],
            connections: [connection('c-keep', 10), connection('c-orphan', 7)],
        };

        const result = clearStaleIds(previous, current);

        expect(result.connections.find((c) => c.id === 'c-keep')!.data?.id).toBe(10);
        expect(result.connections.find((c) => c.id === 'c-orphan')!.data).toBeNull();
    });

    it('is a no-op when there are no stale ids', () => {
        const previous: FlowModel = {
            nodes: [node('x', 1)],
            connections: [connection('c', 2)],
        };
        const current: FlowModel = {
            nodes: [node('x', 1), node('new', null)],
            connections: [connection('c', 2)],
        };

        const result = clearStaleIds(previous, current);

        expect(result.nodes.find((n) => n.id === 'x')!.backendId).toBe(1);
        expect(result.nodes.find((n) => n.id === 'new')!.backendId).toBeNull();
        expect(result.connections[0].data?.id).toBe(2);
    });
});
