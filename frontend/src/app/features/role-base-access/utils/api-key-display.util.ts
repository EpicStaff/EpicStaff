import { ApiKeyStatus, GetMyApiKeyResponse } from '@shared/models';
import { daysUntil } from '@shared/utils';

/** Urgency shown next to the expiry label — mapped to a CSS class by the caller. */
export type ApiKeyExpiryUrgency = 'default' | 'orange' | 'red';

/**
 * User-facing label for `expires_at`:
 *  - `Expired` when the key's status is `EXPIRED` or the date is in the past
 *  - `Never` when the key never expires
 *  - `in N day(s)` otherwise
 */
export function apiKeyExpiresLabel(key: GetMyApiKeyResponse): string {
    if (key.status === ApiKeyStatus.EXPIRED) return 'Expired';
    if (!key.expires_at) return 'Never';
    const days = daysUntil(key.expires_at);
    if (days <= 0) return 'Expired';
    return `in ${days} ${days === 1 ? 'day' : 'days'}`;
}

/**
 * Urgency for an active key's upcoming expiry:
 *  - `red` when ≤ 3 days remain
 *  - `orange` when ≤ 7 days remain
 *  - `default` otherwise (non-active, no expiry, or > 7 days)
 */
export function apiKeyExpiryUrgency(key: GetMyApiKeyResponse): ApiKeyExpiryUrgency {
    if (key.status !== ApiKeyStatus.ACTIVE || !key.expires_at) return 'default';
    const days = daysUntil(key.expires_at);
    if (days <= 0) return 'default';
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
