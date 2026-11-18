import { normalizeIana } from '@shared/components';

// The browser time zone the audit tables show their times in, e.g. "+02:00 Europe/Kyiv".
export function buildTimeZoneLabel(): string {
    // some browsers still report the legacy 'Europe/Kiev' name
    const zone = normalizeIana(Intl.DateTimeFormat().resolvedOptions().timeZone);
    const offsetMinutes = -new Date().getTimezoneOffset();
    const sign = offsetMinutes < 0 ? '-' : '+';
    const absolute = Math.abs(offsetMinutes);
    const hours = String(Math.floor(absolute / 60)).padStart(2, '0');
    const minutes = String(absolute % 60).padStart(2, '0');
    return `${sign}${hours}:${minutes} ${zone}`;
}
