import { combineAuditDateTime, splitAuditDateTime } from './audit-date-time.util';

// Expected values are built with local-time Date constructors, so the specs pass in any time zone.
describe('combineAuditDateTime', () => {
    it('starts a date-only lower bound at 00:00', () => {
        expect(combineAuditDateTime({ date: '05.10.2026', time: '' }, 'from')).toBe(
            new Date(2026, 9, 5, 0, 0, 0, 0).toISOString()
        );
    });

    it('ends a date-only upper bound at 23:59:59.999 so the chosen day is included', () => {
        expect(combineAuditDateTime({ date: '05.10.2026', time: '' }, 'to')).toBe(
            new Date(2026, 9, 5, 23, 59, 59, 999).toISOString()
        );
    });

    it('uses the chosen time on both sides of a range, including the whole upper minute', () => {
        expect(combineAuditDateTime({ date: '01.10.2026', time: '09:30' }, 'from')).toBe(
            new Date(2026, 9, 1, 9, 30, 0, 0).toISOString()
        );
        expect(combineAuditDateTime({ date: '05.10.2026', time: '18:00' }, 'to')).toBe(
            new Date(2026, 9, 5, 18, 0, 59, 999).toISOString()
        );
    });

    it('has no bound when the date is empty, even with a time', () => {
        expect(combineAuditDateTime({ date: '', time: '10:00' }, 'from')).toBeNull();
        expect(combineAuditDateTime({ date: '', time: '' }, 'to')).toBeNull();
    });

    it('is incomplete while the date or time is half typed or invalid', () => {
        expect(combineAuditDateTime({ date: '05.10.20', time: '' }, 'from')).toBeUndefined();
        expect(combineAuditDateTime({ date: '31.02.2026', time: '' }, 'from')).toBeUndefined();
        expect(combineAuditDateTime({ date: '05.10.2026', time: '10:' }, 'to')).toBeUndefined();
        expect(combineAuditDateTime({ date: '05.10.2026', time: '25:00' }, 'to')).toBeUndefined();
    });
});

describe('splitAuditDateTime', () => {
    it('round-trips a combined value in the local time zone', () => {
        const parts = { date: '05.10.2026', time: '14:30' };
        expect(splitAuditDateTime(combineAuditDateTime(parts, 'from')!)).toEqual(parts);
        expect(splitAuditDateTime(combineAuditDateTime(parts, 'to')!)).toEqual(parts);
    });

    it('shows the implicit end of day for a date-only upper bound', () => {
        expect(splitAuditDateTime(combineAuditDateTime({ date: '05.10.2026', time: '' }, 'to')!)).toEqual({
            date: '05.10.2026',
            time: '23:59',
        });
    });

    it('is empty for a missing or unparsable value', () => {
        expect(splitAuditDateTime(null)).toEqual({ date: '', time: '' });
        expect(splitAuditDateTime('not a date')).toEqual({ date: '', time: '' });
    });
});
