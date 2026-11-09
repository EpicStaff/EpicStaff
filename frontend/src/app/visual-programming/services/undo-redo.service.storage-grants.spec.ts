import { TestBed } from '@angular/core/testing';

import { toggleStorageGrant } from '../core/helpers/storage-grants.util';
import { FlowModel } from '../core/models/flow.model';
import { NodeModel } from '../core/models/node.model';
import { mapPythonNodeToModel } from '../utils/load/nodes/python-node.mapper';
import { getNodeDiff } from '../utils/save/diff';
import { FlowService } from './flow.service';
import { UndoRedoService } from './undo-redo.service';

function flowOf(node: NodeModel): FlowModel {
    return { nodes: [node], connections: [] };
}

describe('undoing a file access change on a not-configured node', () => {
    it('brings the grants back to all null, so a save sends nothing for the node', () => {
        const flowService = TestBed.inject(FlowService);
        const undoRedo = TestBed.inject(UndoRedoService);
        const stored = mapPythonNodeToModel({
            id: 7,
            graph: 1,
            uuid: null,
            node_name: 'Python #1',
            node_number: 1,
            python_code: { id: 3, code: 'def main(): return 1', entrypoint: 'main', venv_id: null },
            input_map: {},
            test_input: {},
            output_variable_path: null,
            metadata: {},
            use_storage: false,
            created_at: '2026-01-01T00:00:00Z',
            created_by: null,
            last_edited_by: null,
            last_edited_at: null,
            storage_grant_read: null,
            storage_grant_write: null,
            storage_grant_delete: null,
        });
        flowService.setFlow(flowOf(stored));

        undoRedo.stateChanged();
        flowService.updateNode({ ...stored, storageGrants: toggleStorageGrant(stored.storageGrants, 'read', true) });
        expect(flowService.nodes()[0].storageGrants).toEqual({ read: true, write: false, delete: false });

        undoRedo.onUndo();

        const restored = flowService.nodes()[0];
        expect(restored.storageGrants).toEqual({ read: null, write: null, delete: null });
        const diff = getNodeDiff(flowOf(stored), flowOf(restored));
        expect(
            Object.values(diff).flatMap((entry) => [...entry.toCreate, ...entry.toUpdate, ...entry.toDelete])
        ).toEqual([]);
    });
});
