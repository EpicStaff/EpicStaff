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

// target and parent types are open-ended labels ("python node", "flow"), matched only as a whole
export const USER_ACTION_TYPE_OPERATORS: AuditFilterOp[] = ['equals', 'not_equal'];

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
        { kind: 'select', field: 'action', label: 'Action', options: USER_ACTION_OPTIONS },
        { kind: 'lookup', field: 'actor_user_id', label: 'User', source: 'members', compile: compileMembers },
        { kind: 'text', field: 'target_type', label: 'Target type', operators: USER_ACTION_TYPE_OPERATORS },
        { kind: 'text', field: 'target_name', label: 'Target name', operators: USER_ACTION_TEXT_OPERATORS },
        // keyed apart from the sessions `flow` filter, whose chip clears a different part of the state
        { kind: 'lookup', field: 'flow_id', label: 'Flow', source: 'flows', compile: compileFlows },
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
