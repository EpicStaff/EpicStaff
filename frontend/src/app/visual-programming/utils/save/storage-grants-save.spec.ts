import { GetClassificationDecisionTableNodeRequest } from '../../core/models/classification-decision-table-node.model';
import { GetFileExtractorNodeRequest } from '../../core/models/file-extractor.model';
import { FlowModel } from '../../core/models/flow.model';
import { ClassificationDecisionTableNodeModel, NodeModel, PythonNodeModel } from '../../core/models/node.model';
import { PythonNode } from '../../core/models/python-node.model';
import { StorageGrants } from '../../core/models/storage-grants.model';
import { mapClassificationDecisionTableNodeToModel } from '../load/nodes/classification-decision-table-node.mapper';
import { mapFileExtractorNodeToModel } from '../load/nodes/file-extractor-node.mapper';
import { mapPythonNodeToModel } from '../load/nodes/python-node.mapper';
import { getNodeDiff } from './diff';
import { buildBulkSavePayload } from './payload';

const PYTHON_DTO: PythonNode = {
    id: 7,
    graph: 1,
    uuid: null,
    node_name: 'Python #1',
    node_number: 1,
    python_code: { id: 3, code: 'def main():\n    return 1', entrypoint: 'main', venv_id: null },
    input_map: {},
    test_input: {},
    output_variable_path: null,
    metadata: {},
    use_storage: false,
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    last_edited_by: null,
    last_edited_at: null,
};

const CDT_DTO: GetClassificationDecisionTableNodeRequest = {
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    last_edited_by: null,
    last_edited_at: null,
    id: 21,
    graph: 1,
    uuid: null,
    node_number: 1,
    node_name: 'Triage',
    pre_python_code: null,
    pre_input_map: {},
    pre_output_variable_path: null,
    pre_use_storage: false,
    post_python_code: null,
    post_input_map: {},
    post_output_variable_path: null,
    post_use_storage: false,
    prompt_configs: [],
    default_llm_config: null,
    default_next_node_id: null,
    next_error_node_id: null,
    condition_groups: [],
    metadata: {},
};

const FILE_EXTRACTOR_DTO: GetFileExtractorNodeRequest = {
    id: 9,
    graph: 1,
    uuid: null,
    node_name: 'Extractor #1',
    node_number: 1,
    input_map: {},
    output_variable_path: null,
    metadata: {},
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    last_edited_by: null,
    last_edited_at: null,
};

function flow(nodes: NodeModel[]): FlowModel {
    return { nodes, connections: [] };
}

/** What a save sends for `list` when `previous` is edited into `current`; nothing when no node changed. */
function savedItems(list: string, previous: NodeModel, current: NodeModel): Record<string, unknown>[] {
    const payload = buildBulkSavePayload(
        1,
        getNodeDiff(flow([previous]), flow([current])),
        { toCreate: [], toDelete: [], toUpdate: [] },
        flow([current]),
        new Map(),
        1
    );
    return payload[list] as Record<string, unknown>[];
}

function renamed<T extends NodeModel>(node: T): T {
    return { ...node, node_name: 'Renamed' };
}

describe('python node storage grants save', () => {
    it('keeps the stored grants as they are', () => {
        const loaded = mapPythonNodeToModel({
            ...PYTHON_DTO,
            storage_grant_read: true,
            storage_grant_write: false,
            storage_grant_delete: true,
        });

        const [item] = savedItems('python_node_list', loaded, renamed(loaded));

        expect(item).toMatchObject({
            storage_grant_read: true,
            storage_grant_write: false,
            storage_grant_delete: true,
        });
    });

    it('sends all three flags after a user ticks one box', () => {
        const loaded = mapPythonNodeToModel({
            ...PYTHON_DTO,
            storage_grant_read: false,
            storage_grant_write: false,
            storage_grant_delete: false,
        });
        const ticked: PythonNodeModel = { ...loaded, storageGrants: { read: false, write: true, delete: false } };

        const [item] = savedItems('python_node_list', loaded, ticked);

        expect(item).toMatchObject({
            storage_grant_read: false,
            storage_grant_write: true,
            storage_grant_delete: false,
        });
    });

    it('saves a node whose only change is a grant', () => {
        const loaded = mapPythonNodeToModel({
            ...PYTHON_DTO,
            storage_grant_read: false,
            storage_grant_write: false,
            storage_grant_delete: false,
        });
        const grants: StorageGrants = { read: true, write: false, delete: false };

        expect(savedItems('python_node_list', loaded, { ...loaded, storageGrants: grants })).toHaveLength(1);
        expect(savedItems('python_node_list', loaded, { ...loaded })).toHaveLength(0);
    });

    it('leaves the columns out when the server sent none of them', () => {
        const loaded = mapPythonNodeToModel(PYTHON_DTO);

        const [item] = savedItems('python_node_list', loaded, renamed(loaded));

        expect(Object.keys(item).filter((key) => key.startsWith('storage_grant'))).toEqual([]);
    });
});

describe('file extractor storage grants save', () => {
    it('file extractor sends no storage grant keys', () => {
        const loaded = mapFileExtractorNodeToModel({
            ...FILE_EXTRACTOR_DTO,
            storage_grant_read: true,
            storage_grant_write: true,
            storage_grant_delete: true,
        } as GetFileExtractorNodeRequest);

        const [item] = savedItems('file_extractor_node_list', loaded, renamed(loaded));

        expect(item).toBeDefined();
        expect(Object.keys(item).filter((key) => key.includes('storage_grant'))).toEqual([]);
    });
});

describe('classification decision table storage grants save', () => {
    it('round-trips the pre and post slots independently', () => {
        const loaded: ClassificationDecisionTableNodeModel = mapClassificationDecisionTableNodeToModel({
            ...CDT_DTO,
            pre_storage_grant_read: true,
            pre_storage_grant_write: false,
            pre_storage_grant_delete: false,
            post_storage_grant_read: false,
            post_storage_grant_write: true,
            post_storage_grant_delete: false,
        });

        const [item] = savedItems('classification_decision_table_node_list', loaded, renamed(loaded));

        expect(item).toMatchObject({
            pre_storage_grant_read: true,
            pre_storage_grant_write: false,
            pre_storage_grant_delete: false,
            post_storage_grant_read: false,
            post_storage_grant_write: true,
            post_storage_grant_delete: false,
        });
    });

    it('saves a node whose only change is its post slot', () => {
        const loaded = mapClassificationDecisionTableNodeToModel({
            ...CDT_DTO,
            pre_storage_grant_read: false,
            pre_storage_grant_write: false,
            pre_storage_grant_delete: false,
            post_storage_grant_read: false,
            post_storage_grant_write: false,
            post_storage_grant_delete: false,
        });
        const edited = { ...loaded, postStorageGrants: { read: false, write: false, delete: true } };

        const [item] = savedItems('classification_decision_table_node_list', loaded, edited);

        expect(item).toMatchObject({ post_storage_grant_delete: true, pre_storage_grant_delete: false });
    });
});
