import { purgeDate, timeLeftLabel } from './recycle-bin-time.util';

describe('recycle bin time left', () => {
    const deletedAt = new Date('2026-10-06T18:00:00Z');
    const after = (hours: number, minutes = 0) => new Date(deletedAt.getTime() + hours * 3_600_000 + minutes * 60_000);

    it('counts down in days and hours', () => {
        expect(timeLeftLabel(deletedAt, 7, after(19))).toBe('6 d 5 h');
        expect(timeLeftLabel(deletedAt, 7, after(24))).toBe('6 d');
    });

    it('shows hours, then minutes, on the last day', () => {
        expect(timeLeftLabel(deletedAt, 7, after(7 * 24 - 5))).toBe('5 h');
        expect(timeLeftLabel(deletedAt, 7, after(7 * 24 - 1, 15))).toBe('45 min');
    });

    it('says the purge is due once the time is up', () => {
        expect(timeLeftLabel(deletedAt, 7, after(7 * 24))).toBe('Any moment now');
        expect(timeLeftLabel(deletedAt, 7, after(8 * 24))).toBe('Any moment now');
    });

    it('puts the purge date retention days after the deletion', () => {
        expect(purgeDate(deletedAt, 7).toISOString()).toBe('2026-10-13T18:00:00.000Z');
    });
});
