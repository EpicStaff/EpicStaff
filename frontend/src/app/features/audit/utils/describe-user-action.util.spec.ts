import { AuditUserAction } from '../models/audit-user-action.models';
import { userActionLabel, userActionParent, userActionTarget } from './describe-user-action.util';

const baseAction: AuditUserAction = {
    id: 'action-1',
    org_id: 1,
    event_time: '2026-10-30T10:00:00Z',
    record_time: null,
    filter_matched: true,
    actor_user_id: 3,
    actor_email: 'ann@example.com',
    actor_api_key_name: null,
    action: 'updated',
    target_type: null,
    target_id: null,
    target_name: null,
    previous_name: null,
    parent_type: null,
    parent_id: null,
    parent_name: null,
    route: null,
};

describe('userActionLabel', () => {
    it.each([
        ['updated', 'Updated'],
        ['permanently_deleted', 'Permanently deleted'],
        ['sign_in_failed', 'Sign-in failed'],
        ['import_entity', 'Import entity'],
        ['upload_stream', 'Upload stream'],
        ['register_webhook', 'Register webhook'],
    ])('labels %s as %s', (action, expected) => {
        expect(userActionLabel(action)).toBe(expected);
    });
});

describe('userActionTarget', () => {
    it.each<[string, Partial<AuditUserAction>, string]>([
        [
            'a named target',
            { target_type: 'python node', target_id: '12', target_name: 'Parse invoice' },
            'python node "Parse invoice"',
        ],
        [
            'a rename',
            { action: 'renamed', target_type: 'flow', target_name: 'Billing', previous_name: 'Invoices v2' },
            'flow "Invoices v2" → "Billing"',
        ],
        [
            'a rename that kept no old name',
            { action: 'renamed', target_type: 'flow', target_name: 'Billing' },
            'flow "Billing"',
        ],
        ['a target known only by its id', { action: 'deleted', target_type: 'tool', target_id: '9' }, 'tool #9'],
        ['a target known only by its type', { target_type: 'profile' }, 'profile'],
        ['no target', { action: 'signed_in' }, ''],
    ])('describes %s', (_case, change, expected) => {
        expect(userActionTarget({ ...baseAction, ...change })).toBe(expected);
    });
});

describe('userActionParent', () => {
    it.each<[string, Partial<AuditUserAction>, string]>([
        ['a named parent', { parent_type: 'flow', parent_id: '4', parent_name: 'Billing' }, 'in flow "Billing"'],
        ['a parent known only by its id', { parent_type: 'flow', parent_id: '4' }, 'in flow #4'],
        ['no parent', { target_type: 'flow', target_name: 'Billing' }, ''],
    ])('describes %s', (_case, change, expected) => {
        expect(userActionParent({ ...baseAction, ...change })).toBe(expected);
    });
});
