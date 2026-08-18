import { ApiKeyStatus, GetMyApiKeyResponse } from '@shared/models';
import { daysUntil } from '@shared/utils';

/** Urgency shown next to the expiry label — mapped to a CSS class by the caller. */
export type ApiKeyExpiryUrgency = 'default' | 'orange' | 'red';

/**
 * User-facing label for `expires_at`:
 *  - `Expired` when the key's status is `EXPIRED` or the timestamp is in the past
 *  - `Never` when the key never expires
 *  - `in N day(s)` when ≥ 1 calendar day remains
 *  - `in N hour(s)` / `in N minute(s)` when less than a day remains but the key is still active
 */
export function apiKeyExpiresLabel(key: GetMyApiKeyResponse): string {
    if (key.status === ApiKeyStatus.EXPIRED) return 'Expired';
    if (!key.expires_at) return 'Never';
    const msLeft = new Date(key.expires_at).getTime() - Date.now();
    if (msLeft <= 0) return 'Expired';
    const days = daysUntil(key.expires_at);
    if (days >= 1) return `in ${days} ${days === 1 ? 'day' : 'days'}`;
    const hours = Math.floor(msLeft / (1000 * 60 * 60));
    if (hours >= 1) return `in ${hours} ${hours === 1 ? 'hour' : 'hours'}`;
    const minutes = Math.max(1, Math.floor(msLeft / (1000 * 60)));
    return `in ${minutes} ${minutes === 1 ? 'minute' : 'minutes'}`;
}

/**
 * Urgency for an active key's upcoming expiry:
 *  - `red` when ≤ 3 days remain (including sub-day windows while the key is still active)
 *  - `orange` when ≤ 7 days remain
 *  - `default` otherwise (non-active, no expiry, already past the expiry timestamp, or > 7 days)
 */
export function apiKeyExpiryUrgency(key: GetMyApiKeyResponse): ApiKeyExpiryUrgency {
    if (key.status !== ApiKeyStatus.ACTIVE || !key.expires_at) return 'default';
    const msLeft = new Date(key.expires_at).getTime() - Date.now();
    if (msLeft <= 0) return 'default';
    const days = daysUntil(key.expires_at);
    if (days <= 3) return 'red';
    if (days <= 7) return 'orange';
    return 'default';
}

/** Human-readable label for an API-key status. */
export function apiKeyStatusLabel(status: ApiKeyStatus): string {
    const labels: Record<ApiKeyStatus, string> = {
        [ApiKeyStatus.ACTIVE]: 'Active',
        [ApiKeyStatus.EXPIRED]: 'Expired',
        [ApiKeyStatus.REVOKED]: 'Revoked',
    };
    return labels[status] ?? status;
}

/**
 * Sort-order weight for each API-key status.
 * Active keys sort first, expired second, revoked last.
 * Usage: `keys.sort((a, b) => API_KEY_STATUS_ORDER.get(a.status)! - API_KEY_STATUS_ORDER.get(b.status)!)`
 */
export const API_KEY_STATUS_ORDER = new Map<ApiKeyStatus, number>([
    [ApiKeyStatus.ACTIVE, 0],
    [ApiKeyStatus.EXPIRED, 1],
    [ApiKeyStatus.REVOKED, 2],
]);

/** Icon name for the status badge (null when the badge should render its default dot). */
export function apiKeyStatusIcon(status: ApiKeyStatus): string | null {
    const icons: Partial<Record<ApiKeyStatus, string>> = {
        [ApiKeyStatus.EXPIRED]: 'expired',
        [ApiKeyStatus.REVOKED]: 'x',
    };
    return icons[status] ?? null;
}
