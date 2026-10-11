import { NodeType } from '@shared/models';

import { GraphDto } from '../../../features/flows/models/graph.model';
import { FlowModel } from '../../core/models/flow.model';
import { GetKeyValueNodeRequest } from '../../core/models/key-value-node.model';
import { KeyValueNodeModel } from '../../core/models/node.model';
import { mapKeyValueNodeToModel } from '../load/nodes/key-value-node.mapper';
import { getNodeDiff } from './diff';
import { patchFlowStateWithBackendIds } from './patch';
import { buildBulkSavePayload } from './payload';

const dto: GetKeyValueNodeRequest = {
    id: 12,
    graph: 1,
    node_name: 'Key-Value #1',
    key_value_table: 3,
    mode: 'write',
    entries: [{ key: 'profile_{variables.user.id}', value: 'variables.profile' }],
    input_map: {},
    output_variable_path: 'variables.saved',
    metadata: {},
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    last_edited_by: null,
    last_edited_at: null,
};

describe('key-value node save/load', () => {
    it('maps a DTO to a node model', () => {
        const model = mapKeyValueNodeToModel(dto);
        expect(model.type).toBe(NodeType.KEY_VALUE);
        expect(model.backendId).toBe(12);
        expect(model.data).toEqual({ key_value_table: 3, mode: 'write', entries: dto.entries });
        expect(model.input_map).toEqual(dto.input_map);
    });

    it('loads and saves read entries as key and target path, with no output variable path', () => {
        // jsonb hands the keys back sorted, which here is already key, value.
        const readDto: GetKeyValueNodeRequest = {
            ...dto,
            mode: 'read',
            entries: [{ key: 'profile', value: 'variables.profile' }],
        };
        const loaded = mapKeyValueNodeToModel(readDto);
        const created: KeyValueNodeModel = { ...loaded, backendId: null };
        const current = { nodes: [created], connections: [] } as unknown as FlowModel;
        const diff = getNodeDiff({ nodes: [], connections: [] } as unknown as FlowModel, current);

        const payload = buildBulkSavePayload(
            1,
            diff,
            { toCreate: [], toDelete: [], toUpdate: [] },
            current,
            new Map(),
            1
        );

        expect(loaded.output_variable_path).toBeNull();
        expect(payload['key_value_node_list']).toEqual([
            expect.objectContaining({
                mode: 'read',
                entries: [{ key: 'profile', value: 'variables.profile' }],
                output_variable_path: null,
            }),
        ]);
    });

    it('detects a mode change as an update', () => {
        const before = mapKeyValueNodeToModel(dto);
        const after: KeyValueNodeModel = {
            ...before,
            data: { ...before.data, mode: 'delete', entries: [{ key: 'k' }] },
        };
        const previous = { nodes: [before], connections: [] } as unknown as Parameters<typeof getNodeDiff>[0];
        const current = { nodes: [after], connections: [] } as unknown as Parameters<typeof getNodeDiff>[1];

        const diff = getNodeDiff(previous, current);

        expect(diff.keyValueNodes.toUpdate.map((update) => update.current.backendId)).toEqual([12]);
    });

    it('sends new and deleted nodes under the contract keys and patches the new backendId', () => {
        const existing = mapKeyValueNodeToModel(dto);
        const created: KeyValueNodeModel = { ...mapKeyValueNodeToModel({ ...dto, id: 0 }), backendId: null };
        const previous = { nodes: [existing], connections: [] } as unknown as FlowModel;
        const current = { nodes: [created], connections: [] } as unknown as FlowModel;
        const diff = getNodeDiff(previous, current);

        const payload = buildBulkSavePayload(
            1,
            diff,
            { toCreate: [], toDelete: [], toUpdate: [] },
            current,
            new Map(),
            1
        );

        expect(payload['key_value_node_list']).toEqual([
            expect.objectContaining({ id: null, temp_id: created.id, key_value_table: 3, mode: 'write' }),
        ]);
        expect((payload['deleted'] as Record<string, unknown>)['key_value_node_ids']).toEqual([12]);

        const responseGraph = { key_value_node_list: [{ ...dto, id: 40 }] } as unknown as GraphDto;
        const patched = patchFlowStateWithBackendIds(current, previous, diff, responseGraph);

        expect(patched.nodes[0].backendId).toBe(40);
    });
});
