import { AuditFilterState, EMPTY_AUDIT_FILTER } from '../models/audit-filter.models';
import { mergeSavedFilterState } from './audit-preset-body.util';

const ANY_VERSION_KEY_PREFIX = 'epicstaff.audit.filter.';
// Bump the version whenever AuditFilterState changes shape, so a stale stored state is dropped instead of loaded.
const CURRENT_VERSION_KEY_PREFIX = `${ANY_VERSION_KEY_PREFIX}v1.`;

// 'applied' is the filter the table runs; 'draft' is the panel selection not applied yet.
export type AuditFilterStorageKind = 'applied' | 'draft';

// A filter belongs to one user in one organization: another person signing in to that organization in the same
// browser must not get it. Without both ids there is no owner, so nothing is stored.
export function auditFilterStorageKey(
    organizationId: number | null,
    userId: number | null,
    kind: AuditFilterStorageKind
): string | null {
    if (organizationId === null || userId === null) {
        return null;
    }
    return `${CURRENT_VERSION_KEY_PREFIX}${kind}.${organizationId}.${userId}`;
}

export function readStoredAuditFilter(
    key: string | null,
    fallback: AuditFilterState = EMPTY_AUDIT_FILTER
): AuditFilterState {
    if (key === null) {
        return fallback;
    }
    try {
        const raw = localStorage.getItem(key);
        const saved: unknown = raw === null ? null : JSON.parse(raw);
        if (typeof saved === 'object' && saved !== null && !Array.isArray(saved)) {
            return mergeSavedFilterState(saved as Partial<AuditFilterState>);
        }
    } catch {
        // Unreadable or blocked storage falls back to the fallback filter.
    }
    return fallback;
}

export function writeStoredAuditFilter(key: string | null, state: AuditFilterState): void {
    if (key === null) {
        return;
    }
    try {
        localStorage.setItem(key, JSON.stringify(state));
    } catch {
        // Full or blocked storage only costs persistence across reloads.
    }
}

/** Removes every stored audit filter: all organizations and users, applied and draft, current and older formats. */
export function clearStoredAuditFilters(): void {
    try {
        const auditFilterKeys = Array.from({ length: localStorage.length }, (_, index) =>
            localStorage.key(index)
        ).filter((key): key is string => key?.startsWith(ANY_VERSION_KEY_PREFIX) ?? false);
        auditFilterKeys.forEach((key) => localStorage.removeItem(key));
    } catch {
        // Blocked storage holds nothing to clear.
    }
}
