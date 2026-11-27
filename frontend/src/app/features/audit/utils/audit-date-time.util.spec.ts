import { combineAuditDateTime, splitAuditDateTime } from './audit-date-time.util';

// A zone other than UTC, so a value read on the wrong clock shows; expectations are the UTC instants.
const ZONE = 'America/New_York';

describe('combineAuditDateTime', () => {
    it('starts a date-only lower bound at 00:00', () => {
        expect(combineAuditDateTime({ date: '05.10.2026', time: '' }, 'from', ZONE)).toBe('2026-10-05T04:00:00.000Z');
    });

    it('ends a date-only upper bound at 23:59:59.999 so the chosen day is included', () => {
        expect(combineAuditDateTime({ date: '05.10.2026', time: '' }, 'to', ZONE)).toBe('2026-10-06T03:59:59.999Z');
    });

    it('uses the chosen time on both sides of a range, including the whole upper minute', () => {
        expect(combineAuditDateTime({ date: '01.10.2026', time: '09:30' }, 'from', ZONE)).toBe(
            '2026-10-01T13:30:00.000Z'
        );
        expect(combineAuditDateTime({ date: '05.10.2026', time: '18:00' }, 'to', ZONE)).toBe(
            '2026-10-05T22:00:59.999Z'
        );
    });

    it('audit filter converts typed times using the display zone', () => {
        expect(combineAuditDateTime({ date: '05.10.2026', time: '14:30' }, 'from', 'Asia/Tokyo')).toBe(
            '2026-10-05T05:30:00.000Z'
        );
    });

    it('covers the whole day the clocks change on', () => {
        // Europe/Kyiv starts the day on winter time (+02:00) and ends it on summer time (+03:00).
        expect(combineAuditDateTime({ date: '29.03.2026', time: '' }, 'from', 'Europe/Kyiv')).toBe(
            '2026-03-28T22:00:00.000Z'
        );
        expect(combineAuditDateTime({ date: '29.03.2026', time: '' }, 'to', 'Europe/Kyiv')).toBe(
            '2026-03-29T20:59:59.999Z'
        );
    });

    it('has no bound when the date is empty, even with a time', () => {
        expect(combineAuditDateTime({ date: '', time: '10:00' }, 'from', ZONE)).toBeNull();
        expect(combineAuditDateTime({ date: '', time: '' }, 'to', ZONE)).toBeNull();
    });

    it('is incomplete while the date or time is half typed or invalid', () => {
        expect(combineAuditDateTime({ date: '05.10.20', time: '' }, 'from', ZONE)).toBeUndefined();
        expect(combineAuditDateTime({ date: '31.02.2026', time: '' }, 'from', ZONE)).toBeUndefined();
        expect(combineAuditDateTime({ date: '05.10.2026', time: '10:' }, 'to', ZONE)).toBeUndefined();
        expect(combineAuditDateTime({ date: '05.10.2026', time: '25:00' }, 'to', ZONE)).toBeUndefined();
    });
});

describe('splitAuditDateTime', () => {
    it('shows a stored bound on the clock of the display zone', () => {
        expect(splitAuditDateTime('2026-10-05T18:30:00.000Z', ZONE)).toEqual({ date: '05.10.2026', time: '14:30' });
        expect(splitAuditDateTime('2026-10-05T18:30:00.000Z', 'Asia/Tokyo')).toEqual({
            date: '06.10.2026',
            time: '03:30',
        });
    });

    it('round-trips a combined value in the same zone', () => {
        const parts = { date: '05.10.2026', time: '14:30' };
        expect(splitAuditDateTime(combineAuditDateTime(parts, 'from', ZONE)!, ZONE)).toEqual(parts);
        expect(splitAuditDateTime(combineAuditDateTime(parts, 'to', ZONE)!, ZONE)).toEqual(parts);
    });

    it('shows the implicit end of day for a date-only upper bound', () => {
        expect(splitAuditDateTime(combineAuditDateTime({ date: '05.10.2026', time: '' }, 'to', ZONE)!, ZONE)).toEqual({
            date: '05.10.2026',
            time: '23:59',
        });
    });

    it('is empty for a missing or unparsable value', () => {
        expect(splitAuditDateTime(null, ZONE)).toEqual({ date: '', time: '' });
        expect(splitAuditDateTime('not a date', ZONE)).toEqual({ date: '', time: '' });
    });
});
