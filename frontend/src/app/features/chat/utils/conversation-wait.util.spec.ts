import { isOverdue } from './conversation-wait.util';

// Local wall-clock times, so the rules hold in any time zone the tests run in.
const at = (year: number, month: number, day: number, hours = 0, minutes = 0): Date =>
    new Date(year, month - 1, day, hours, minutes);
// Monday 12 October 2026, 14:30.
const NOW = at(2026, 10, 12, 14, 30).getTime();

describe('isOverdue', () => {
    const tenMinutes = 10 * 60_000;
    const since = at(2026, 10, 12, 14, 20).toISOString();

    it('marks a wait past the response time, not one that has just reached it', () => {
        expect(isOverdue(since, tenMinutes, NOW - 1)).toBe(false);
        expect(isOverdue(since, tenMinutes, NOW)).toBe(false);
        expect(isOverdue(since, tenMinutes, NOW + 1)).toBe(true);
    });

    it('marks nothing on a desk that does not mark overdue, nor without a usable wait', () => {
        expect(isOverdue(since, null, NOW + 60 * 60_000)).toBe(false);
        expect(isOverdue(null, tenMinutes, NOW)).toBe(false);
        expect(isOverdue(undefined, tenMinutes, NOW)).toBe(false);
        expect(isOverdue('not a time', tenMinutes, NOW)).toBe(false);
    });
});
