import { AuditUserAction } from '../models/audit-user-action.models';
import { describeUserAction } from './describe-user-action.util';

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

describe('describeUserAction', () => {
    it.each<[string, Partial<AuditUserAction>, string]>([
        [
            'a change inside a parent',
            {
                action: 'updated',
                target_type: 'python node',
                target_id: '12',
                target_name: 'Parse invoice',
                parent_type: 'flow',
                parent_id: '4',
                parent_name: 'Billing',
            },
            'updated python node "Parse invoice" in flow "Billing"',
        ],
        [
            'a rename',
            { action: 'renamed', target_type: 'flow', target_name: 'Billing', previous_name: 'Invoices v2' },
            'renamed flow "Invoices v2" → "Billing"',
        ],
        ['a sign-in', { action: 'signed_in' }, 'signed in'],
        ['a failed sign-in', { action: 'sign_in_failed' }, 'sign-in failed'],
        [
            'a permanent delete',
            { action: 'permanently_deleted', target_type: 'agent', target_name: 'Old summariser' },
            'permanently deleted agent "Old summariser"',
        ],
        [
            'a fallback record',
            { action: 'copy', target_type: 'flow', target_name: 'Billing', route: 'POST api/graphs/<pk>/copy/' },
            'copy flow "Billing"',
        ],
        [
            'a fallback action named with underscores',
            { action: 'import_entity', target_type: 'flow', target_name: 'Billing' },
            'import entity flow "Billing"',
        ],
        [
            'a target known only by its id',
            { action: 'deleted', target_type: 'tool', target_id: '9' },
            'deleted tool #9',
        ],
    ])('describes %s', (_case, change, expected) => {
        expect(describeUserAction({ ...baseAction, ...change })).toBe(expected);
    });
});
