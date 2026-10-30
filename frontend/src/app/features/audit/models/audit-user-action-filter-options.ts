import { AuditFieldCatalog } from './audit-domain.models';
import { AuditEnumOption, AuditFilterOp } from './audit-filter.models';

// The actions the recorder writes, then the DRF action names the fallback records most often carry.
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
    { value: 'create', label: 'create' },
    { value: 'update', label: 'update' },
    { value: 'partial_update', label: 'partial_update' },
    { value: 'destroy', label: 'destroy' },
    { value: 'copy', label: 'copy' },
    { value: 'import_entity', label: 'import_entity' },
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

export const USER_ACTION_FIELD_CATALOG: AuditFieldCatalog = {
    domain: 'user_actions',
    builderFields: [
        { kind: 'select', field: 'action', label: 'Action', options: USER_ACTION_OPTIONS },
        { kind: 'text', field: 'actor_email', label: 'Who', operators: USER_ACTION_TEXT_OPERATORS },
        { kind: 'text', field: 'target_type', label: 'Target type', operators: USER_ACTION_TYPE_OPERATORS },
        { kind: 'text', field: 'target_name', label: 'Target name', operators: USER_ACTION_TEXT_OPERATORS },
        { kind: 'text', field: 'parent_type', label: 'Parent type', operators: USER_ACTION_TYPE_OPERATORS },
        { kind: 'text', field: 'parent_name', label: 'Parent name', operators: USER_ACTION_TEXT_OPERATORS },
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
