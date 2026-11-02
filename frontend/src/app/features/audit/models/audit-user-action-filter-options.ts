import { AuditFieldCatalog } from './audit-domain.models';
import { AuditEnumOption, AuditFilterNode, AuditFilterOp, AuditValuesFilter } from './audit-filter.models';

// The actions the recorder writes, then the custom backend actions the fallback records most often carry;
// generic API creates, updates and deletes are recorded as created, updated and deleted.
export const USER_ACTION_OPTIONS: AuditEnumOption[] = [
    { value: 'created', label: 'Created' },
    { value: 'updated', label: 'Updated' },
    { value: 'renamed', label: 'Renamed' },
    { value: 'deleted', label: 'Deleted' },
    { value: 'restored', label: 'Restored' },
    { value: 'permanently_deleted', label: 'Permanently deleted' },
    { value: 'signed_in', label: 'Signed in' },
    { value: 'sign_in_failed', label: 'Sign-in failed' },
    { value: 'signed_out', label: 'Signed out' },
    { value: 'password_reset', label: 'Password reset' },
    { value: 'copy', label: 'Copy' },
    { value: 'import_entity', label: 'Import entity' },
];

export const USER_ACTION_TEXT_OPERATORS: AuditFilterOp[] = [
    'contains',
    'not_contains',
    'starts_with',
    'ends_with',
    'equals',
    'not_equal',
    'is_empty',
    'is_not_empty',
];

function compileMembers({ op, values }: AuditValuesFilter): AuditFilterNode {
    return { field: 'actor_user_id', op, value: values.map(Number) };
}

// A flow is recorded as the target of its own actions and as the parent of its nodes', so picking it
// finds both; matching by id keeps a flow renamed since the record was written.
function compileFlows({ op, values }: AuditValuesFilter): AuditFilterNode {
    const recordsOfFlow = (typeField: string, idField: string): AuditFilterNode => ({
        op: 'and',
        children: [
            { field: typeField, op: 'equals', value: 'flow' },
            { field: idField, op: 'in', value: values },
        ],
    });
    const anyOf: AuditFilterNode = {
        op: 'or',
        children: [recordsOfFlow('target_type', 'target_id'), recordsOfFlow('parent_type', 'parent_id')],
    };
    return op === 'not_in' ? { op: 'not', child: anyOf } : anyOf;
}

export const USER_ACTION_FIELD_CATALOG: AuditFieldCatalog = {
    domain: 'user_actions',
    builderFields: [
        { kind: 'select', field: 'action', label: 'Action', section: 'quick', options: USER_ACTION_OPTIONS },
        {
            kind: 'lookup',
            field: 'actor_user_id',
            label: 'User',
            section: 'quick',
            source: 'members',
            compile: compileMembers,
        },
        // target types are open-ended ("python node", "flow"), so the tab loads the ones recorded
        { kind: 'select', field: 'target_type', label: 'Target Type', section: 'quick', source: 'targetTypes' },
        // keyed apart from the sessions `flow` filter, whose chip clears a different part of the state
        { kind: 'lookup', field: 'flow_id', label: 'Flow', section: 'quick', source: 'flows', compile: compileFlows },
        {
            kind: 'text',
            field: 'target_name',
            label: 'Target Name',
            section: 'deep',
            operators: USER_ACTION_TEXT_OPERATORS,
        },
    ],
    queryFields: [
        'action',
        'actor_email',
        'actor_api_key_name',
        'actor_user_id',
        'target_type',
        'target_name',
        'target_id',
        'previous_name',
        'parent_type',
        'parent_name',
        'parent_id',
        'route',
        'event_time',
    ],
    queryExamples: [
        'action in ("deleted", "permanently_deleted")',
        'actor_email : "@example.com" and target_type == "flow"',
        'action == "sign_in_failed" and event_time >= "2026-01-01T00:00:00Z"',
        'actor_api_key_name == "CI bot"',
    ],
    queryPlaceholder: 'e.g. action in (deleted) and target_type == "flow"',
};
