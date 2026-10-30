import { CDTPythonCodeBlock } from '../../core/models/classification-decision-table-node.model';
import { FlowModel } from '../../core/models/flow.model';
import { NodeModel } from '../../core/models/node.model';
import { PythonNode } from '../../core/models/python-node.model';
import { GetWebhookTriggerNodeRequest } from '../../core/models/webhook-trigger';
import { mapClassificationDecisionTableNodeToModel } from '../load/nodes/classification-decision-table-node.mapper';
import { mapPythonNodeToModel } from '../load/nodes/python-node.mapper';
import { mapWebhookTriggerNodeToModel } from '../load/nodes/webhook-trigger-node.mapper';
import { getNodeDiff } from './diff';
import { buildBulkSavePayload } from './payload';

// The editor does not edit these, so a save sends them back as stored: the backend replaces what it is
// given, and refuses changing them on code that reads secrets for a user without Secrets:Use.
const STORED = { entrypoint: 'run', global_kwargs: { retries: 3 } };

const AUTHORSHIP = { created_by: null, last_edited_by: null, last_edited_at: null };

const PYTHON: PythonNode = {
    ...AUTHORSHIP,
    id: 7,
    graph: 1,
    node_name: 'Python #1',
    node_number: 1,
    python_code: { id: 3, code: 'def run(): pass', ...STORED },
    input_map: {},
    test_input: {},
    output_variable_path: null,
    metadata: {},
    use_storage: false,
    created_at: '2026-01-01T00:00:00Z',
};

const WEBHOOK: GetWebhookTriggerNodeRequest = {
    ...AUTHORSHIP,
    id: 8,
    graph: 1,
    node_name: 'Webhook #1',
    node_number: 2,
    python_code: { id: 4, code: 'def run(trigger_payload): pass', ...STORED },
    input_map: {},
    output_variable_path: null,
    webhook_trigger_path: '',
    metadata: {},
    webhook_trigger: null,
    test_payload: {},
    use_storage: false,
    created_at: '2026-01-01T00:00:00Z',
};

function cdtBlock(code: string, stored: Partial<CDTPythonCodeBlock> = STORED): CDTPythonCodeBlock {
    return { code, entrypoint: 'main', global_kwargs: {}, ...stored };
}

function cdt(preBlock: CDTPythonCodeBlock) {
    return mapClassificationDecisionTableNodeToModel({
        ...AUTHORSHIP,
        id: 9,
        graph: 1,
        node_number: 3,
        node_name: 'Triage',
        pre_python_code: preBlock,
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
        created_at: '2026-01-01T00:00:00Z',
    });
}

/** The one node list item a save of `loaded`, renamed, would send. */
function savedRenamed(loaded: NodeModel, listKey: string): Record<string, unknown> {
    const renamed = { ...loaded, node_name: 'Renamed' } as NodeModel;
    const current: FlowModel = { nodes: [renamed], connections: [] };
    const payload = buildBulkSavePayload(
        1,
        getNodeDiff({ nodes: [loaded], connections: [] }, current),
        { toCreate: [], toDelete: [], toUpdate: [] },
        current,
        new Map(),
        1
    );
    return (payload[listKey] as Record<string, unknown>[])[0];
}

describe('stored entrypoint and global kwargs of Python code on save', () => {
    it.each([
        { node: 'python', loaded: () => mapPythonNodeToModel(PYTHON), list: 'python_node_list', key: 'python_code' },
        {
            node: 'webhook trigger',
            loaded: () => mapWebhookTriggerNodeToModel(WEBHOOK),
            list: 'webhook_trigger_node_list',
            key: 'python_code',
        },
        {
            node: 'classification table',
            loaded: () => cdt(cdtBlock('def run(): pass')),
            list: 'classification_decision_table_node_list',
            key: 'pre_python_code',
        },
    ])('sends back the stored ones of a loaded $node node', ({ loaded, list, key }) => {
        const sentCode = savedRenamed(loaded(), list)[key] as Record<string, unknown>;

        expect(sentCode['entrypoint']).toBe('run');
        expect(sentCode['global_kwargs']).toEqual({ retries: 3 });
    });

    it('sends the defaults for classification table code the backend has not stored them for', () => {
        const loaded = cdt(cdtBlock('def main(): pass'));
        const preComputation = loaded.data.table.pre_computation!;
        const withoutStored = {
            ...loaded,
            data: {
                ...loaded.data,
                table: {
                    ...loaded.data.table,
                    pre_computation: { ...preComputation, entrypoint: undefined, global_kwargs: undefined },
                },
            },
        };

        const sentCode = savedRenamed(withoutStored, 'classification_decision_table_node_list')[
            'pre_python_code'
        ] as Record<string, unknown>;

        expect(sentCode['entrypoint']).toBe('main');
        expect(sentCode['global_kwargs']).toEqual({});
    });
});
