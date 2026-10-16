import { auditHistoryRangeToDays, formatAuditHistoryDays, splitAuditHistoryDays } from './audit-history.util';

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
