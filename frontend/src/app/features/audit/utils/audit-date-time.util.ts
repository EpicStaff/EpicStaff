// Joins the date picker (dd.mm.yyyy) and time picker (hh:mm) values into the ISO string the date filter
// stores, and splits it back for display. Both directions work in the browser's local time zone.

// `from` is the inclusive lower bound (gte), `to` the inclusive upper bound (lte).
export type AuditDateBoundary = 'from' | 'to';

export interface AuditDateTimeParts {
    date: string;
    time: string;
}

const DATE_PATTERN = /^(\d{2})\.(\d{2})\.(\d{4})$/;
const TIME_PATTERN = /^(\d{2}):(\d{2})$/;

// Returns null when the date is empty (no bound on that side) and undefined while a field is incomplete or
// invalid, so the caller keeps the previous value instead of emitting a half-typed one.
export function combineAuditDateTime(
    parts: AuditDateTimeParts,
    boundary: AuditDateBoundary
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

    // An empty time covers the whole day: from its first minute, or to its last.
    const time = parts.time || (boundary === 'from' ? '00:00' : '23:59');
    const timeMatch = TIME_PATTERN.exec(time);
    if (!timeMatch) {
        return undefined;
    }
    const hours = Number(timeMatch[1]);
    const minutes = Number(timeMatch[2]);
    if (hours > 23 || minutes > 59) {
        return undefined;
    }

    // The upper bound includes the whole chosen minute, so "to 23:59" is the end of the day.
    const date =
        boundary === 'from'
            ? new Date(year, month, day, hours, minutes, 0, 0)
            : new Date(year, month, day, hours, minutes, 59, 999);
    if (date.getFullYear() !== year || date.getMonth() !== month || date.getDate() !== day) {
        return undefined;
    }
    return date.toISOString();
}

export function splitAuditDateTime(iso: string | null): AuditDateTimeParts {
    const date = iso ? new Date(iso) : null;
    if (!date || Number.isNaN(date.getTime())) {
        return { date: '', time: '' };
    }
    return {
        date: `${pad(date.getDate())}.${pad(date.getMonth() + 1)}.${date.getFullYear()}`,
        time: `${pad(date.getHours())}:${pad(date.getMinutes())}`,
    };
}

function pad(value: number): string {
    return String(value).padStart(2, '0');
}
