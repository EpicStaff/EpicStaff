import { buildTimeZoneLabel } from './audit-time-zone-label.util';

describe('buildTimeZoneLabel', () => {
    it.each([
        ['America/New_York', '2026-07-01T12:00:00Z', '-04:00 America/New_York'],
        ['Asia/Kolkata', '2026-07-01T12:00:00Z', '+05:30 Asia/Kolkata'],
        ['UTC', '2026-07-01T12:00:00Z', '+00:00 UTC'],
    ])('audit label shows the chosen zone offset (%s on %s)', (zone, now, expected) => {
        expect(buildTimeZoneLabel(zone, new Date(now))).toBe(expected);
    });

    it('follows the zone across its daylight-saving switch', () => {
        expect(buildTimeZoneLabel('Europe/Kyiv', new Date('2026-03-29T00:30:00Z'))).toBe('+02:00 Europe/Kyiv');
        expect(buildTimeZoneLabel('Europe/Kyiv', new Date('2026-03-29T02:30:00Z'))).toBe('+03:00 Europe/Kyiv');
    });
});
