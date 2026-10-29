import { RestoreWarning } from '../../../features/flows/models/graph.model';
import { SnapshotNode } from '../../../features/flows/models/graph-version-preview.model';
import { FIELD_DISPLAY, FieldName } from './field-display';
import { buildVersionKeyValueTableNames, buildVersionWarningReferences } from './version-side-inputs';

const snapshotIdToCanvasId = new Map([
    [5, 'node-a-canvas-id'],
    [6, 'node-b-canvas-id'],
    [13, 'node-c-canvas-id'],
]);

function warning(type: string, extra: Partial<RestoreWarning>): RestoreWarning {
    return { type, reason: 'Referenced entity no longer exists.', ...extra };
}

describe('buildVersionWarningReferences', () => {
    it('turns node-anchored warnings into missing references on the projected path of their canvas node', () => {
        const references = buildVersionWarningReferences(
            [
                warning('fk_nulled', { node_id: 5, field: 'agent_definition', missing_id: 41 }),
                warning('surface_dropped', { node_id: 5, missing_id: 51 }),
                warning('inline_tool_dropped', { node_id: 6, missing_id: 21 }),
                warning('decision_table_ref_cleared', {
                    node_id: 13,
                    field: 'default_next_node_id',
                    missing_node_id: 2,
                }),
                warning('decision_table_ref_cleared', { node_id: 13, field: 'next_error_node_id', missing_node_id: 3 }),
                warning('decision_table_ref_cleared', {
                    node_id: 13,
                    field: 'condition_groups[yes].next_node_id',
                    missing_node_id: 4,
                }),
            ],
            snapshotIdToCanvasId
        );

        const reference = (path: string, field: string, missing: number) => ({
            path,
            field,
            missing,
            source: 'warning',
        });
        expect(references).toEqual(
            new Map([
                [
                    'node-a-canvas-id',
                    [
                        reference('agent_definition', 'agent_definition', 41),
                        reference('surface_list', 'surface_list', 51),
                    ],
                ],
                ['node-b-canvas-id', [reference('inline_surface', 'inline_surface', 21)]],
                [
                    'node-c-canvas-id',
                    [
                        reference('default_next_node', 'default_next_node', 2),
                        reference('next_error_node', 'next_error_node', 3),
                        reference('condition_groups[name=yes].next_node', 'condition_groups[].next_node', 4),
                    ],
                ],
            ])
        );
    });

    it.each([
        ['python_code', 'python_code.secret_names'],
        ['pre_python_code', 'pre_computation.secret_names'],
        ['post_python_code', 'post_computation.secret_names'],
        ['telegram_bot_api_key_secret', 'telegram_bot_api_key_secret_id'],
    ])(
        'turns a dropped secret declaration of `%s` into a missing reference on `%s`, by secret name',
        (backendField, path) => {
            const references = buildVersionWarningReferences(
                [warning('secret_declaration_dropped', { node_id: 5, field: backendField, missing_name: 'GONE_KEY' })],
                snapshotIdToCanvasId
            );

            expect(references).toEqual(
                new Map([['node-a-canvas-id', [{ path, field: path, missing: 'GONE_KEY', source: 'warning' }]]])
            );
        }
    );

    it('skips a dropped secret declaration whose field the diff does not project', () => {
        const references = buildVersionWarningReferences(
            [warning('secret_declaration_dropped', { node_id: 5, field: 'other_code', missing_name: 'GONE_KEY' })],
            snapshotIdToCanvasId
        );

        expect(references).toEqual(new Map());
    });

    it.each([
        ['python_code', 'python_code.venv_id'],
        ['pre_python_code', 'pre_computation.venv_id'],
        ['post_python_code', 'post_computation.venv_id'],
    ])('turns a cleared venv of `%s` into a missing reference on `%s`, by venv id', (backendField, path) => {
        const references = buildVersionWarningReferences(
            [warning('venv_ref_cleared', { node_id: 5, field: backendField, missing_id: 31 })],
            snapshotIdToCanvasId
        );

        expect(references).toEqual(
            new Map([['node-a-canvas-id', [{ path, field: path, missing: 31, source: 'warning' }]]])
        );
    });

    it('skips a cleared venv whose code field it does not know', () => {
        const references = buildVersionWarningReferences(
            [warning('venv_ref_cleared', { node_id: 5, field: 'other_code', missing_id: 31 })],
            snapshotIdToCanvasId
        );

        expect(references).toEqual(new Map());
    });

    // The backend nulls exactly these foreign keys today (its `NullFkHandler` subclasses). A new handler
    // must be added here, and its field must be a projected `FieldName`, or its reference gets no label.
    const BACKEND_FK_NULLED_FIELDS = [
        'subgraph',
        'webhook_trigger',
        'agent_definition',
    ] as const satisfies readonly FieldName[];

    it.each(BACKEND_FK_NULLED_FIELDS)('anchors an `fk_nulled` warning on `%s` to that projected field', (field) => {
        const references = buildVersionWarningReferences(
            [warning('fk_nulled', { node_id: 5, field, missing_id: 7 })],
            snapshotIdToCanvasId
        );

        expect(FIELD_DISPLAY).toHaveProperty([field]);
        expect(references.get('node-a-canvas-id')).toEqual([{ path: field, field, missing: 7, source: 'warning' }]);
    });

    it('keeps a warning that carries no missing id, with `missing` null', () => {
        const references = buildVersionWarningReferences(
            [warning('surface_dropped', { node_id: 5 })],
            snapshotIdToCanvasId
        );

        expect(references.get('node-a-canvas-id')).toEqual([
            { path: 'surface_list', field: 'surface_list', missing: null, source: 'warning' },
        ]);
    });

    it('leaves graph-level warnings and nodes missing from the canvas to the warnings banner', () => {
        const references = buildVersionWarningReferences(
            [
                warning('edge_dropped', {}),
                warning('node_type_unsupported', { node_type: 'LLMNode' }),
                warning('fk_nulled', { node_id: 999, field: 'subgraph', missing_id: 3 }),
                warning('fk_nulled', { node_id: 5 }),
            ],
            snapshotIdToCanvasId
        );

        expect(references).toEqual(new Map());
    });
});

describe('buildVersionKeyValueTableNames', () => {
    it('keeps the stored table name of Key-Value nodes that had one, keyed by canvas id', () => {
        const keyValueNode = (id: number, tableName: string | null): SnapshotNode =>
            ({ id, node_type: 'KeyValueNode', key_value_table: null, key_value_table_name: tableName }) as SnapshotNode;

        const tableNames = buildVersionKeyValueTableNames(
            [
                keyValueNode(5, 'Customers'),
                keyValueNode(6, null),
                keyValueNode(999, 'Not on the canvas'),
                { id: 13, node_type: 'DecisionTableNode' } as SnapshotNode,
            ],
            snapshotIdToCanvasId
        );

        expect(tableNames).toEqual(new Map([['node-a-canvas-id', 'Customers']]));
    });
});
