import { formatDate } from '@angular/common';

import {
    formatInZone,
    instantFromZonedWallTime,
    knownZone,
    WallTime,
    zonedCalendarDaysBetween,
    zonedWallTime,
    zoneOffsetMinutes,
} from './zoned-date.util';

const wall = (year: number, month: number, day: number, hours: number, minutes: number): WallTime => ({
    year,
    month: month - 1,
    day,
    hours,
    minutes,
    seconds: 0,
    milliseconds: 0,
});

describe('zoneOffsetMinutes', () => {
    it.each([
        ['Europe/Kyiv in winter', '2026-01-15T12:00:00Z', 'Europe/Kyiv', 120],
        ['Europe/Kyiv in summer', '2026-07-01T12:00:00Z', 'Europe/Kyiv', 180],
        ['America/New_York in summer', '2026-07-01T12:00:00Z', 'America/New_York', -240],
        ['a half-hour zone', '2026-07-01T12:00:00Z', 'Asia/Kolkata', 330],
        ['UTC', '2026-07-01T12:00:00Z', 'UTC', 0],
    ])('is the offset of %s', (_case, iso, zone, expected) => {
        expect(zoneOffsetMinutes(new Date(iso), zone)).toBe(expected);
    });
});

describe('formatInZone', () => {
    it.each([
        ['2026-07-01T12:00:00Z', 'HH:mm', 'America/New_York', '08:00'],
        ['2026-07-01T12:00:00Z', 'MMM d, y, HH:mm', 'Asia/Tokyo', 'Jul 1, 2026, 21:00'],
        // The day changes with the zone, not only the clock.
        ['2026-07-01T02:00:00Z', 'MMM d, EEE', 'America/Los_Angeles', 'Jun 30, Tue'],
        // The zone's own offset, not the browser's.
        ['2026-07-01T12:00:00Z', 'HH:mm Z', 'America/New_York', '08:00 -0400'],
        ['2026-07-01T12:00:00.250Z', 'HH:mm:ss.SSS', 'UTC', '12:00:00.250'],
    ])('formats %s as %s in %s', (iso, format, zone, expected) => {
        expect(formatInZone(iso, format, 'en-US', zone)).toBe(expected);
    });

    it('formats across the DST switch in Europe/Kyiv', () => {
        // Clocks go from 03:00 to 04:00 local time at 01:00 UTC on 29 March 2026.
        expect(formatInZone('2026-03-29T00:30:00Z', 'HH:mm', 'en-US', 'Europe/Kyiv')).toBe('02:30');
        expect(formatInZone('2026-03-29T02:30:00Z', 'HH:mm', 'en-US', 'Europe/Kyiv')).toBe('05:30');
    });

    it('accepts a Date and a timestamp as well as an ISO string', () => {
        const instant = Date.parse('2026-07-01T12:00:00Z');
        expect(formatInZone(new Date(instant), 'HH:mm', 'en-US', 'Asia/Tokyo')).toBe('21:00');
        expect(formatInZone(instant, 'HH:mm', 'en-US', 'Asia/Tokyo')).toBe('21:00');
    });

    it('shows a calendar day without a time as it is, in any zone', () => {
        expect(formatInZone('2026-07-01', 'MMM d, y', 'en-US', 'Pacific/Honolulu')).toBe('Jul 1, 2026');
        expect(formatInZone('2026-07-01', 'MMM d, y', 'en-US', 'Pacific/Kiritimati')).toBe('Jul 1, 2026');
    });

    it("falls back to the browser's zone for a zone this browser does not know", () => {
        const iso = '2026-07-01T12:00:00Z';
        expect(formatInZone(iso, 'HH:mm', 'en-US', 'Mars/Olympus_Mons')).toBe(formatDate(iso, 'HH:mm', 'en-US'));
    });
});

describe('instantFromZonedWallTime', () => {
    it.each([
        ['an ordinary reading', wall(2026, 10, 5, 14, 30), 'Europe/Kyiv', '2026-10-05T11:30:00.000Z'],
        ['a reading in a zone behind UTC', wall(2026, 7, 1, 8, 0), 'America/New_York', '2026-07-01T12:00:00.000Z'],
        // 01:30 shows twice on 1 November 2026 in New York: first on summer time, then on winter time.
        [
            'a reading shown twice, as the first',
            wall(2026, 11, 1, 1, 30),
            'America/New_York',
            '2026-11-01T05:30:00.000Z',
        ],
        // 02:30 never shows on 8 March 2026 in New York (02:00 → 03:00); it is taken as 03:30 summer time.
        ['a skipped reading, past the switch', wall(2026, 3, 8, 2, 30), 'America/New_York', '2026-03-08T07:30:00.000Z'],
    ])('places %s', (_case, reading, zone, expected) => {
        expect(instantFromZonedWallTime(reading, zone).toISOString()).toBe(expected);
    });

    it('reads back as the same wall time', () => {
        const reading = wall(2026, 3, 29, 2, 30);
        expect(zonedWallTime(instantFromZonedWallTime(reading, 'Europe/Kyiv'), 'Europe/Kyiv')).toEqual(reading);
    });
});

describe('zonedCalendarDaysBetween', () => {
    const earlier = new Date('2026-10-12T14:00:00Z');
    const later = new Date('2026-10-12T16:00:00Z');

    it.each([
        // 23:00 and 01:00 the next day in Tokyo.
        ['Asia/Tokyo', 1],
        ['UTC', 0],
    ])('counts calendar days in %s', (zone, expected) => {
        expect(zonedCalendarDaysBetween(earlier, later, zone)).toBe(expected);
    });
});

describe('knownZone', () => {
    it('keeps a zone this browser knows, and drops one it does not', () => {
        expect(knownZone('Europe/Kyiv')).toBe('Europe/Kyiv');
        expect(knownZone('Mars/Olympus_Mons')).toBeUndefined();
    });
});
