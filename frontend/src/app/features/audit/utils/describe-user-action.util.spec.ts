import { AuditUserAction } from '../models/audit-user-action.models';
import {
    userActionLabel,
    userActionParentName,
    userActionTargetName,
    userActionTone,
    userActionTypeLabel,
} from './describe-user-action.util';

const baseAction: AuditUserAction = {
    id: 'action-1',
    org_id: 1,
    event_time: '2026-10-30T10:00:00Z',
    record_time: null,
    filter_matched: true,
    number: 1,
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
        ['moved_to_recycle_bin', 'Moved to Recycle Bin'],
        ['sign_in_failed', 'Sign-in failed'],
        ['import_entity', 'Import entity'],
        ['paused', 'Paused'],
        ['resumed', 'Resumed'],
        ['key_rotated', 'Key rotated'],
        ['deactivated', 'Deactivated'],
        ['reactivated', 'Reactivated'],
        ['superadmin_granted', 'Superadmin granted'],
        ['superadmin_revoked', 'Superadmin revoked'],
        ['upload_stream', 'Upload stream'],
        ['register_webhook', 'Register webhook'],
    ])('labels %s as %s', (action, expected) => {
        expect(userActionLabel(action)).toBe(expected);
    });
});

describe('userActionTargetName', () => {
    it.each<[string, Partial<AuditUserAction>, string]>([
        [
            'a named target',
            { target_type: 'python node', target_id: '12', target_name: 'Parse invoice' },
            'Parse invoice',
        ],
        [
            'a rename',
            { action: 'renamed', target_type: 'flow', target_name: 'Billing', previous_name: 'Invoices v2' },
            'Invoices v2 → Billing',
        ],
        [
            'a move',
            {
                action: 'moved',
                target_type: 'storage file',
                target_name: 'reports/q3.pdf',
                previous_name: 'inbox/q3.pdf',
            },
            'inbox/q3.pdf → reports/q3.pdf',
        ],
        [
            'a copy, from its source to the new copy',
            { action: 'copied', target_type: 'flow', target_name: 'Billing (copy)', previous_name: 'Billing' },
            'Billing → Billing (copy)',
        ],
        [
            'a member update that kept the old role',
            { action: 'updated', target_type: 'member', target_name: 'ann@example.com', previous_name: 'Viewer' },
            'ann@example.com',
        ],
        [
            'a rename that kept no old name',
            { action: 'renamed', target_type: 'flow', target_name: 'Billing' },
            'Billing',
        ],
        ['a target known only by its id', { action: 'deleted', target_type: 'tool', target_id: '9' }, '#9'],
        ['a target known only by its type', { target_type: 'profile' }, ''],
        ['no target', { action: 'signed_in' }, ''],
    ])('describes %s', (_case, change, expected) => {
        expect(userActionTargetName({ ...baseAction, ...change })).toBe(expected);
    });
});

describe('userActionParentName', () => {
    it.each<[string, Partial<AuditUserAction>, string]>([
        ['a named flow', { parent_type: 'flow', parent_id: '4', parent_name: 'Billing' }, 'Billing'],
        ['a named agent', { parent_type: 'agent', parent_id: '7', parent_name: 'Researcher' }, 'Researcher'],
        ['a flow known only by its id', { parent_type: 'flow', parent_id: '12' }, '#12'],
        ['a parent known only by its type', { parent_type: 'flow' }, ''],
        ['no parent', { target_type: 'flow', target_name: 'Billing' }, ''],
    ])('describes %s', (_case, change, expected) => {
        expect(userActionParentName({ ...baseAction, ...change })).toBe(expected);
    });
});

describe('userActionTypeLabel', () => {
    it.each<[string | null, string]>([
        ['python node', 'Python node'],
        ['flow', 'Flow'],
        ['desk', 'Desk'],
        [null, ''],
    ])('labels %s as "%s"', (type, expected) => {
        expect(userActionTypeLabel(type)).toBe(expected);
    });
});

describe('userActionTone', () => {
    it.each<[string, string]>([
        ['created', 'added'],
        ['restored', 'added'],
        ['updated', 'changed'],
        ['renamed', 'changed'],
        ['moved', 'changed'],
        ['copied', 'added'],
        ['resumed', 'added'],
        ['key_rotated', 'changed'],
        ['paused', 'alert'],
        ['deactivated', 'alert'],
        ['reactivated', 'added'],
        ['superadmin_granted', 'alert'],
        ['superadmin_revoked', 'changed'],
        ['moved_to_recycle_bin', 'removed'],
        ['deleted', 'destroyed'],
        ['sign_in_failed', 'destroyed'],
        ['password_reset', 'alert'],
        ['signed_in', 'plain'],
        ['import_entity', 'plain'],
    ])('gives %s the %s tone', (action, tone) => {
        expect(userActionTone(action)).toBe(tone);
    });
});
