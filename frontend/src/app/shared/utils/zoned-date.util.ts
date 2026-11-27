import { formatDate } from '@angular/common';

/** A wall-clock reading in some zone. `month` is 0-based, as in `Date`. */
export interface WallTime {
    readonly year: number;
    readonly month: number;
    readonly day: number;
    readonly hours: number;
    readonly minutes: number;
    readonly seconds: number;
    readonly milliseconds: number;
}

const MINUTE_MS = 60_000;
const DAY_MS = 24 * 60 * MINUTE_MS;

// What Angular's `date` pipe reads as a calendar day with no time: it has no zone to convert from.
const CALENDAR_DAY_PATTERN = /^\d{4}(-\d{1,2}(-\d{1,2})?)?$/;
const NUMERIC_PATTERN = /^-?\d+(\.\d+)?$/;

// Building a formatter is slow and the date pipe runs on every change detection, so there is one per zone.
const wallClockFormatters = new Map<string, Intl.DateTimeFormat | null>();

/**
 * The wall clock of `zone` at `instant`. `null` when this browser does not know the zone (an older browser may not
 * know a newer name), so the caller can fall back to the browser's own zone instead of breaking the page.
 */
export function zonedWallTime(instant: Date, zone: string): WallTime | null {
    const formatter = wallClockFormatter(zone);
    if (formatter === null) return null;
    const parts = formatter.formatToParts(instant);
    const part = (type: Intl.DateTimeFormatPartTypes): number =>
        Number(parts.find((candidate) => candidate.type === type)?.value);
    return {
        year: part('year'),
        month: part('month') - 1,
        day: part('day'),
        hours: part('hour'),
        minutes: part('minute'),
        seconds: part('second'),
        milliseconds: ((instant.getTime() % 1000) + 1000) % 1000,
    };
}

/**
 * `zone` for the `timeZone` option of `toLocale*String`, or `undefined` (the browser's zone) when this browser does
 * not know it, where the option would throw.
 */
export function knownZone(zone: string): string | undefined {
    return wallClockFormatter(zone) === null ? undefined : zone;
}

/** Minutes `zone` is ahead of UTC at `instant` (east positive): +120 for Europe/Kyiv in winter, +180 in summer. */
export function zoneOffsetMinutes(instant: Date, zone: string): number {
    const wall = zonedWallTime(instant, zone);
    if (wall === null) return -instant.getTimezoneOffset();
    return Math.round((wallTimeAsUtc(wall) - instant.getTime()) / MINUTE_MS);
}

/**
 * The instant the wall clock of `zone` reads `wall`. A reading the clock skips when it springs forward is taken as
 * the same distance past the switch (02:30 on a 02:00→03:00 day is 03:30); a reading it shows twice when it falls back
 * is taken as the first one.
 */
export function instantFromZonedWallTime(wall: WallTime, zone: string): Date {
    const asUtc = wallTimeAsUtc(wall);
    // A day apart, the offsets on either side of a switch near the reading; each gives one instant to check.
    const offsetBefore = zoneOffsetMinutes(new Date(asUtc - DAY_MS), zone);
    const offsetAfter = zoneOffsetMinutes(new Date(asUtc + DAY_MS), zone);
    const withBefore = asUtc - offsetBefore * MINUTE_MS;
    const withAfter = asUtc - offsetAfter * MINUTE_MS;
    const showsReading = (instant: number, offset: number): boolean =>
        zoneOffsetMinutes(new Date(instant), zone) === offset;

    if (showsReading(withBefore, offsetBefore)) {
        return new Date(showsReading(withAfter, offsetAfter) ? Math.min(withBefore, withAfter) : withBefore);
    }
    if (showsReading(withAfter, offsetAfter)) return new Date(withAfter);
    // Skipped: the offset from before the switch carries the reading past it by the same distance.
    return new Date(withBefore);
}

/**
 * Formats like Angular's `formatDate`, with the same format strings, but in `zone` (an IANA name) and right across
 * daylight saving. A calendar day with no time ("2026-07-01") has no zone, so it is shown as it is. Throws, as
 * `formatDate` does, on a value that is not a date.
 */
export function formatInZone(value: Date | string | number, format: string, locale: string, zone: string): string {
    if (typeof value === 'string' && CALENDAR_DAY_PATTERN.test(value.trim())) {
        return formatDate(value, format, locale);
    }
    const instant = toInstant(value);
    const wall = Number.isNaN(instant.getTime()) ? null : zonedWallTime(instant, zone);
    if (wall === null) return formatDate(value, format, locale);
    const offsetMinutes = Math.round((wallTimeAsUtc(wall) - instant.getTime()) / MINUTE_MS);
    return formatDate(new WallClockDate(instant.getTime(), wall, offsetMinutes), format, locale);
}

/** The number of calendar days in `zone` from the day of `earlier` to the day of `later`: 1 for yesterday. */
export function zonedCalendarDaysBetween(earlier: Date, later: Date, zone: string): number {
    const dayStart = (instant: Date): number => {
        const wall = zonedWallTime(instant, zone);
        return wall === null
            ? Date.UTC(instant.getFullYear(), instant.getMonth(), instant.getDate())
            : Date.UTC(wall.year, wall.month, wall.day);
    };
    return Math.round((dayStart(later) - dayStart(earlier)) / DAY_MS);
}

/**
 * A date whose local fields read as the wall clock of a zone. Angular's `formatDate` reads a date through its local
 * getters, so formatting this one shows the zone's time and offset. Its own `timezone` argument is not used instead:
 * it shifts the date by the browser's offset, which is an hour off near the browser's own daylight-saving switch.
 */
class WallClockDate extends Date {
    private readonly wall: WallTime;
    private readonly offsetMinutes: number;

    constructor(instant: number, wall: WallTime, offsetMinutes: number) {
        super(instant);
        this.wall = wall;
        this.offsetMinutes = offsetMinutes;
    }

    override getFullYear(): number {
        return this.wall.year;
    }

    override getMonth(): number {
        return this.wall.month;
    }

    override getDate(): number {
        return this.wall.day;
    }

    override getDay(): number {
        return new Date(Date.UTC(this.wall.year, this.wall.month, this.wall.day)).getUTCDay();
    }

    override getHours(): number {
        return this.wall.hours;
    }

    override getMinutes(): number {
        return this.wall.minutes;
    }

    override getSeconds(): number {
        return this.wall.seconds;
    }

    override getMilliseconds(): number {
        return this.wall.milliseconds;
    }

    override getTimezoneOffset(): number {
        return -this.offsetMinutes;
    }
}

function wallClockFormatter(zone: string): Intl.DateTimeFormat | null {
    let formatter = wallClockFormatters.get(zone);
    if (formatter === undefined) {
        try {
            formatter = new Intl.DateTimeFormat('en-US', {
                timeZone: zone,
                hourCycle: 'h23',
                year: 'numeric',
                month: 'numeric',
                day: 'numeric',
                hour: 'numeric',
                minute: 'numeric',
                second: 'numeric',
            });
        } catch {
            formatter = null;
        }
        wallClockFormatters.set(zone, formatter);
    }
    return formatter;
}

function wallTimeAsUtc(wall: WallTime): number {
    const utc = new Date(0);
    // setUTCFullYear keeps years below 100 as they are; Date.UTC would read them as 19xx.
    utc.setUTCFullYear(wall.year, wall.month, wall.day);
    utc.setUTCHours(wall.hours, wall.minutes, wall.seconds, wall.milliseconds);
    return utc.getTime();
}

// The instant Angular's `formatDate` reads from the same value.
function toInstant(value: Date | string | number): Date {
    if (value instanceof Date) return value;
    if (typeof value === 'number') return new Date(value);
    const text = value.trim();
    return NUMERIC_PATTERN.test(text) ? new Date(parseFloat(text)) : new Date(text);
}
