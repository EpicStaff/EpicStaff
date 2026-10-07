import { AuditFilterState, EMPTY_AUDIT_FILTER } from '../models/audit-filter.models';
import { mergeSavedFilterState } from './audit-preset-body.util';

// Bump the version whenever AuditFilterState changes shape, so a stale stored state is dropped instead of loaded.
const STORAGE_KEY_PREFIX = 'epicstaff.audit.filter.v1.';

// 'applied' is the filter the table runs; 'draft' is the panel selection not applied yet.
export type AuditFilterStorageKind = 'applied' | 'draft';

export function auditFilterStorageKey(organizationId: number | null, kind: AuditFilterStorageKind): string | null {
    return organizationId === null ? null : `${STORAGE_KEY_PREFIX}${kind}.${organizationId}`;
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
