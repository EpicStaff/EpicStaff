import { FlowModel } from '../../core/models/flow.model';
import { PythonNodeModel } from '../../core/models/node.model';
import { PythonNode } from '../../core/models/python-node.model';
import { mapPythonNodeToModel } from '../load/nodes/python-node.mapper';
import { getNodeDiff } from './diff';
import { buildBulkSavePayload } from './payload';

const dto: PythonNode = {
    id: 7,
    graph: 1,
    node_name: 'Python #1',
    node_number: 1,
    uuid: '00000000-0000-4000-8000-000000000007',
    python_code: {
        id: 3,
        code: 'def main():\n    return 1',
        entrypoint: 'main',
        venv_id: 12,
    },
    input_map: {},
    test_input: {},
    output_variable_path: 'variables.result',
    metadata: {},
    use_storage: false,
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    last_edited_by: null,
    last_edited_at: null,
};

/** The `python_code` a save would send for the one python node in `current`. */
function savedPythonCode(previous: PythonNodeModel, current: PythonNodeModel): Record<string, unknown> {
    const diff = getNodeDiff(
        { nodes: [previous], connections: [] } as unknown as FlowModel,
        {
            nodes: [current],
            connections: [],
        } as unknown as FlowModel
    );
    const payload = buildBulkSavePayload(
        1,
        diff,
        { toCreate: [], toDelete: [], toUpdate: [] },
        { nodes: [current], connections: [] } as unknown as FlowModel,
        new Map(),
        1
    );
    const [node] = payload['python_node_list'] as Record<string, unknown>[];
    return node['python_code'] as Record<string, unknown>;
}

describe('python node save/load', () => {
    it('keeps the venv of a loaded node when an unrelated field changes', () => {
        // The round trip the editor really does: load the graph, edit something
        // else, save. A venv dropped on load reaches the save as null and silently
        // detaches the node from its environment.
        const loaded = mapPythonNodeToModel(dto);
        const renamed: PythonNodeModel = { ...loaded, node_name: 'Renamed' };

        expect(savedPythonCode(loaded, renamed)['venv_id']).toBe(12);
    });

    it('sends a null venv for a node whose code has none', () => {
        const loaded = mapPythonNodeToModel({ ...dto, python_code: { ...dto.python_code, venv_id: null } });
        const renamed: PythonNodeModel = { ...loaded, node_name: 'Renamed' };

        expect(savedPythonCode(loaded, renamed)['venv_id']).toBeNull();
    });
});
