import { instantFromZonedWallTime, zonedWallTime } from '@shared/utils';

// Joins the date picker (dd.mm.yyyy) and time picker (hh:mm) values into the ISO string the date filter
// stores, and splits it back for display. Both directions read the clock of `zone`, the display timezone the
// table shows its times in, so a typed 14:30 matches a row shown at 14:30.

// `from` is the inclusive lower bound (gte), `to` the inclusive upper bound (lte).
export type AuditDateBoundary = 'from' | 'to';

export interface AuditDateTimeParts {
    date: string;
    time: string;
}

// An empty time covers the whole day: from its first minute, or to its last.
export const AUDIT_DEFAULT_TIME: Record<AuditDateBoundary, string> = { from: '00:00', to: '23:59' };

const DATE_PATTERN = /^(\d{2})\.(\d{2})\.(\d{4})$/;
const TIME_PATTERN = /^(\d{2}):(\d{2})$/;

// Returns null when the date is empty (no bound on that side) and undefined while a field is incomplete or
// invalid, so the caller keeps the previous value instead of emitting a half-typed one.
export function combineAuditDateTime(
    parts: AuditDateTimeParts,
    boundary: AuditDateBoundary,
    zone: string
): string | null | undefined {
    if (!parts.date) {
        return null;
    }
    const dateMatch = DATE_PATTERN.exec(parts.date);
    if (!dateMatch) {
        return undefined;
    }
    const day = Number(dateMatch[1]);
    const month = Number(dateMatch[2]) - 1;
    const year = Number(dateMatch[3]);

    const time = parts.time || AUDIT_DEFAULT_TIME[boundary];
    const timeMatch = TIME_PATTERN.exec(time);
    if (!timeMatch) {
        return undefined;
    }
    const hours = Number(timeMatch[1]);
    const minutes = Number(timeMatch[2]);
    if (hours > 23 || minutes > 59) {
        return undefined;
    }

    // A day the month does not have, such as 31.02, rolls over into the next month.
    const calendarDay = new Date(Date.UTC(year, month, day));
    if (
        calendarDay.getUTCFullYear() !== year ||
        calendarDay.getUTCMonth() !== month ||
        calendarDay.getUTCDate() !== day
    ) {
        return undefined;
    }
    // The upper bound includes the whole chosen minute, so "to 23:59" is the end of the day.
    const seconds = boundary === 'from' ? 0 : 59;
    const milliseconds = boundary === 'from' ? 0 : 999;
    return instantFromZonedWallTime({ year, month, day, hours, minutes, seconds, milliseconds }, zone).toISOString();
}

export function splitAuditDateTime(iso: string | null, zone: string): AuditDateTimeParts {
    const date = iso ? new Date(iso) : null;
    if (!date || Number.isNaN(date.getTime())) {
        return { date: '', time: '' };
    }
    // A zone this browser does not know falls back to the browser's own clock.
    const wall = zonedWallTime(date, zone) ?? {
        year: date.getFullYear(),
        month: date.getMonth(),
        day: date.getDate(),
        hours: date.getHours(),
        minutes: date.getMinutes(),
    };
    return {
        date: `${pad(wall.day)}.${pad(wall.month + 1)}.${wall.year}`,
        time: `${pad(wall.hours)}:${pad(wall.minutes)}`,
    };
}

function pad(value: number): string {
    return String(value).padStart(2, '0');
}
