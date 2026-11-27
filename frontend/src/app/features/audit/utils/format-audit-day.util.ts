import { knownZone } from '@shared/utils';

// The day of an ISO instant in `zone`, as the browser's locale writes it: "Oct 05, 2026" in en-US.
export function formatAuditDay(iso: string, zone: string): string {
    return new Date(iso).toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'short',
        day: '2-digit',
        timeZone: knownZone(zone),
    });
}
