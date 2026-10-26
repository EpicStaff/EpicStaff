import type { PlaceConditions } from './api';

const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;

/** "12.4 °C · 5 min ago", or "—" while Weather has no temperature for the place. `now` in milliseconds. */
export function conditionsText(conditions: PlaceConditions | null, now: number): string {
    if (conditions === null) return '—';
    return `${conditions.temperature_c.toFixed(1)} °C · ${ageText(now - Date.parse(conditions.observed_at))}`;
}

/** How long ago, roughly: "just now", "5 min ago", "2 h ago", "3 days ago". */
function ageText(elapsedMs: number): string {
    if (elapsedMs < MINUTE_MS) return 'just now';
    if (elapsedMs < HOUR_MS) return `${Math.floor(elapsedMs / MINUTE_MS)} min ago`;
    if (elapsedMs < DAY_MS) return `${Math.floor(elapsedMs / HOUR_MS)} h ago`;
    const days = Math.floor(elapsedMs / DAY_MS);
    return days === 1 ? '1 day ago' : `${days} days ago`;
}
