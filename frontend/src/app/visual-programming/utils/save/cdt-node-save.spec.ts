import { CdtExplanation } from '../../core/models/classification-decision-table.model';
import { GetClassificationDecisionTableNodeRequest } from '../../core/models/classification-decision-table-node.model';
import { ConnectionModel } from '../../core/models/connection.model';
import { ConditionGroup } from '../../core/models/decision-table.model';
import { FlowModel } from '../../core/models/flow.model';
import { ClassificationDecisionTableNodeModel, NodeModel } from '../../core/models/node.model';
import { mapClassificationDecisionTableNodeToModel } from '../load/nodes/classification-decision-table-node.mapper';
import { getNodeDiff } from './diff';
import { buildBulkSavePayload } from './payload';

const FIRST: CdtExplanation = { text: 'Sends spam to the bin', fingerprint: 'f1', generatedBy: 'gpt-4o-mini' };
const SECOND: CdtExplanation = { text: 'Routes refunds', fingerprint: 'f2', generatedBy: 'gpt-4o-mini' };

const DTO: GetClassificationDecisionTableNodeRequest = {
    uuid: '00000000-0000-4000-8000-000000000044',
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    last_edited_by: null,
    last_edited_at: null,
    id: 21,
    graph: 1,
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
    condition_groups: [
        {
            id: 1,
            classification_decision_table_node: 21,
            group_name: 'Spam',
            order: 1,
            expression: 'score > 0.9',
            prompt: null,
            manipulation: null,
            continue_flag: false,
            route_code: 'spam',
            dock_visible: true,
            field_expressions: {},
            field_manipulations: {},
        },
    ],
    // Written in the reverse of sorted order, as a store that appended them would.
    metadata: { position: { x: 10, y: 20 }, explanations: { 'rule:route:spam': SECOND, 'node:pre': FIRST } },
};

function load(): ClassificationDecisionTableNodeModel {
    return mapClassificationDecisionTableNodeToModel(DTO);
}

function flow(nodes: NodeModel[], connections: ConnectionModel[] = []): FlowModel {
    return { nodes, connections };
}

function payloadFor(previous: FlowModel, current: FlowModel): Record<string, unknown>[] {
    const payload = buildBulkSavePayload(
        1,
        getNodeDiff(previous, current),
        { toCreate: [], toDelete: [], toUpdate: [] },
        current,
        new Map(),
        1
    );
    return payload['classification_decision_table_node_list'] as Record<string, unknown>[];
}

function withRows(node: ClassificationDecisionTableNodeModel, rows: ConditionGroup[]) {
    return { ...node, data: { ...node.data, table: { ...node.data.table, condition_groups: rows } } };
}

describe('classification decision table save: explanations', () => {
    it('loads explanations from metadata, dropping malformed entries', () => {
        const node = mapClassificationDecisionTableNodeToModel({
            ...DTO,
            metadata: { explanations: { good: FIRST, bad: { text: 1 } } },
        });

        expect(node.explanations).toEqual({ good: FIRST });
    });

    it('is not dirty after a reload that brings the entries back in another order', () => {
        const generated: ClassificationDecisionTableNodeModel = {
            ...load(),
            explanations: { 'node:pre': FIRST, 'rule:route:spam': SECOND },
        };

        const diff = getNodeDiff(flow([load()]), flow([generated]));

        expect(diff.classificationDecisionTableNodes.toUpdate).toEqual([]);
    });

    it('sends a node whose only change is a new explanation', () => {
        const before = load();
        const after: ClassificationDecisionTableNodeModel = {
            ...before,
            explanations: { ...before.explanations, 'rule:name:new': FIRST },
        };

        const diff = getNodeDiff(flow([before]), flow([after]));

        expect(diff.classificationDecisionTableNodes.toUpdate.map((update) => update.current.backendId)).toEqual([21]);
    });

    it('sends a node whose only change is a regenerated explanation', () => {
        const before = load();
        const after: ClassificationDecisionTableNodeModel = {
            ...before,
            explanations: { ...before.explanations, 'node:pre': { ...FIRST, fingerprint: 'f1-new' } },
        };

        expect(getNodeDiff(flow([before]), flow([after])).classificationDecisionTableNodes.toUpdate).toHaveLength(1);
    });

    it('treats a node never explained and one with no explanations left as equal', () => {
        const before: ClassificationDecisionTableNodeModel = { ...load(), explanations: undefined };
        const after: ClassificationDecisionTableNodeModel = { ...load(), explanations: {} };

        expect(getNodeDiff(flow([before]), flow([after])).classificationDecisionTableNodes.toUpdate).toEqual([]);
    });

    it('carries the explanations in metadata, sorted, beside the canvas metadata', () => {
        const before = load();
        const after: ClassificationDecisionTableNodeModel = {
            ...before,
            explanations: { 'rule:route:spam': SECOND, 'node:pre': FIRST, 'node:post': FIRST },
        };

        const [item] = payloadFor(flow([before]), flow([after]));
        const metadata = item['metadata'] as Record<string, unknown>;

        expect(item['id']).toBe(21);
        expect(metadata['position']).toEqual({ x: 10, y: 20 });
        expect(metadata['explanations']).toEqual({ 'node:post': FIRST, 'node:pre': FIRST, 'rule:route:spam': SECOND });
        expect(Object.keys(metadata['explanations'] as object)).toEqual(['node:post', 'node:pre', 'rule:route:spam']);
    });

    it('carries an empty explanations object for a new node never explained', () => {
        const created: ClassificationDecisionTableNodeModel = { ...load(), backendId: null, explanations: undefined };

        const [item] = payloadFor(flow([]), flow([created]));

        expect((item['metadata'] as Record<string, unknown>)['explanations']).toEqual({});
    });
});

describe('classification decision table save: route targets from connections', () => {
    const target = (id: string, backendId: number) => ({ id, backendId }) as unknown as NodeModel;
    const connection = (sourceNodeId: string, sourcePortId: string, targetNodeId: string) =>
        ({ sourceNodeId, sourcePortId, targetNodeId }) as ConnectionModel;

    function rowsOf(item: Record<string, unknown>): Record<string, unknown>[] {
        return item['condition_groups'] as Record<string, unknown>[];
    }

    it('finds the target on the port slugified from the untrimmed route code', () => {
        const node = load();
        const rows: ConditionGroup[] = [
            { ...node.data.table.condition_groups[0], route_code: 'A ', next_node: null, order: 1 },
            { ...node.data.table.condition_groups[0], group_name: 'Plain', route_code: 'A', next_node: null, order: 2 },
        ];
        const current = flow(
            [withRows(node, rows), target('padded', 5), target('plain', 6)],
            [
                connection(node.id, `${node.id}_decision-route-a-`, 'padded'),
                connection(node.id, `${node.id}_decision-route-a`, 'plain'),
            ]
        );

        const [item] = payloadFor(flow([]), { ...current, nodes: current.nodes.map(asNew(node.id)) });

        expect(rowsOf(item).map((group) => [group['route_code'], group['next_node_id']])).toEqual([
            ['A ', 5],
            ['A', 6],
        ]);
    });

    it('collapses inner whitespace and case the way the port generator does', () => {
        const node = load();
        const rows: ConditionGroup[] = [
            { ...node.data.table.condition_groups[0], route_code: 'Needs  Review', next_node: null, order: 1 },
        ];
        const current = flow(
            [withRows(node, rows), target('review', 9)],
            [connection(node.id, `${node.id}_decision-route-needs-review`, 'review')]
        );

        const [item] = payloadFor(flow([]), { ...current, nodes: current.nodes.map(asNew(node.id)) });

        expect(rowsOf(item)[0]['next_node_id']).toBe(9);
    });

    it('sends no target for a row without a route code, even with a connection on its name', () => {
        const node = load();
        const rows: ConditionGroup[] = [
            { ...node.data.table.condition_groups[0], route_code: null, next_node: null, order: 1 },
        ];
        const current = flow(
            [withRows(node, rows), target('stray', 4)],
            [connection(node.id, `${node.id}_decision-route-spam`, 'stray')]
        );

        const [item] = payloadFor(flow([]), { ...current, nodes: current.nodes.map(asNew(node.id)) });

        expect(rowsOf(item)[0]['next_node_id']).toBeNull();
    });
});

/** Marks the table as unsaved so it lands in `toCreate` and is always sent. */
function asNew(tableId: string) {
    return (node: NodeModel): NodeModel => (node.id === tableId ? ({ ...node, backendId: null } as NodeModel) : node);
}
