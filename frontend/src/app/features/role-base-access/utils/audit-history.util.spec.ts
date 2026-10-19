import { ActionCode, RolePermission } from '@shared/models';

import {
    auditHistoryDaysOf,
    auditHistoryRangeToDays,
    formatAuditHistoryDays,
    splitAuditHistoryDays,
    withAuditHistoryDays,
} from './audit-history.util';

describe('audit history days on role permissions', () => {
    const flows: RolePermission = { resource_type: 'flows', actions: [ActionCode.Read] };

    it('reads the limit from the audit entry, unlimited when absent', () => {
        expect(
            auditHistoryDaysOf([flows, { resource_type: 'audit', actions: [ActionCode.Read], audit_history_days: 30 }])
        ).toBe(30);
        expect(auditHistoryDaysOf([flows, { resource_type: 'audit', actions: [ActionCode.Read] }])).toBe(0);
        expect(auditHistoryDaysOf([flows])).toBe(0);
    });

    it('attaches the limit only to an audit entry that grants read or export', () => {
        expect(withAuditHistoryDays([flows, { resource_type: 'audit', actions: [ActionCode.Export] }], 30)).toEqual([
            flows,
            { resource_type: 'audit', actions: [ActionCode.Export], audit_history_days: 30 },
        ]);
    });

    it('does not attach the limit when the audit entry has no read or export', () => {
        const permissions: RolePermission[] = [flows, { resource_type: 'audit', actions: [ActionCode.Delete] }];
        expect(withAuditHistoryDays(permissions, 30)).toEqual(permissions);
        expect(withAuditHistoryDays([flows], 30)).toEqual([flows]);
    });

    it('does not attach an unlimited value', () => {
        const permissions: RolePermission[] = [{ resource_type: 'audit', actions: [ActionCode.Read] }];
        expect(withAuditHistoryDays(permissions, 0)).toEqual(permissions);
    });
});

describe('audit history days', () => {
    it('splits stored days into the largest unit that divides evenly', () => {
        expect(splitAuditHistoryDays(0)).toEqual({ unit: 'unlimited', amount: 1 });
        expect(splitAuditHistoryDays(730)).toEqual({ unit: 'years', amount: 2 });
        expect(splitAuditHistoryDays(180)).toEqual({ unit: 'months', amount: 6 });
        expect(splitAuditHistoryDays(45)).toEqual({ unit: 'days', amount: 45 });
    });

    it('turns a unit and amount back into days', () => {
        expect(auditHistoryRangeToDays({ unit: 'unlimited', amount: 5 })).toBe(0);
        expect(auditHistoryRangeToDays({ unit: 'years', amount: 1 })).toBe(365);
        expect(auditHistoryRangeToDays({ unit: 'months', amount: 6 })).toBe(180);
        expect(auditHistoryRangeToDays({ unit: 'days', amount: 7 })).toBe(7);
    });

    it('formats stored days as a pluralized label', () => {
        expect(formatAuditHistoryDays(0)).toBe('Unlimited');
        expect(formatAuditHistoryDays(1)).toBe('1 day');
        expect(formatAuditHistoryDays(30)).toBe('1 month');
        expect(formatAuditHistoryDays(180)).toBe('6 months');
        expect(formatAuditHistoryDays(365)).toBe('1 year');
        expect(formatAuditHistoryDays(730)).toBe('2 years');
        expect(formatAuditHistoryDays(45)).toBe('45 days');
    });
});
