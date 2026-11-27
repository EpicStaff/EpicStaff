import { zoneOffsetMinutes } from '@shared/utils';

// The zone the audit tables show their times in, with its offset now, e.g. "+02:00 Europe/Kyiv".
export function buildTimeZoneLabel(zone: string, now: Date = new Date()): string {
    const offsetMinutes = zoneOffsetMinutes(now, zone);
    const sign = offsetMinutes < 0 ? '-' : '+';
    const absolute = Math.abs(offsetMinutes);
    const hours = String(Math.floor(absolute / 60)).padStart(2, '0');
    const minutes = String(absolute % 60).padStart(2, '0');
    return `${sign}${hours}:${minutes} ${zone}`;
}
