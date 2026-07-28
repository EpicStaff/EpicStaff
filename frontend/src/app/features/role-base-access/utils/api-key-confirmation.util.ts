import { ConfirmationDialogData } from '@shared/components';
import { ApiKeyStatus } from '@shared/models';

export interface BulkApiKeyItem {
    name: string;
    status: ApiKeyStatus;
}

function keyListHtml(items: BulkApiKeyItem[]): string {
    return `<ul>${items.map((k) => `<li>• ${k.name}</li>`).join('')}</ul>`;
}

/** Single-key revoke — admin view (cross-org messaging). */
export function getAdminRevokeConfirmationData(keyName: string): ConfirmationDialogData {
    return {
        title: 'Revoke key',
        message: `The key <strong>${keyName}</strong> will stop working immediately across <strong>all organizations</strong>. The record will remain in the list for audit purposes.`,
        type: 'danger',
        confirmText: 'Revoke',
        cancelText: 'Cancel',
    };
}

/** Single-key delete — admin view (shows owner name + cross-org messaging). */
export function getAdminDeleteConfirmationData(ownerName: string): ConfirmationDialogData {
    return {
        title: 'Delete key',
        message: `This key belongs to <strong>${ownerName}</strong>. Deleting it will immediately disable it in <strong>all organizations</strong> this user belongs to.`,
        type: 'danger',
        confirmText: 'Delete',
        cancelText: 'Cancel',
    };
}

/** Single-key revoke — profile (personal key) view. */
export function getProfileRevokeConfirmationData(keyName: string): ConfirmationDialogData {
    return {
        title: 'Revoke this API key?',
        message: `The "${keyName}" API key will be revoked immediately and can no longer be used to authenticate.`,
        caution: 'Any client or integration currently using this key will lose access.',
        type: 'danger',
        confirmText: 'Revoke',
        cancelText: 'Cancel',
    };
}

/** Single-key delete — profile (personal key) view. Message and type adapt when the key is still active. */
export function getProfileDeleteConfirmationData(keyName: string, isActive: boolean): ConfirmationDialogData {
    return {
        title: 'Delete this API key?',
        message: `The "${keyName}" API key will be permanently deleted. This action cannot be undone.`,
        caution: isActive ? 'This key is still active — any client currently using it will lose access.' : undefined,
        type: isActive ? 'danger' : 'info',
        confirmText: 'Delete',
        cancelText: 'Cancel',
    };
}

export function getBulkRevokeConfirmationData(items: BulkApiKeyItem[]): ConfirmationDialogData {
    const activeItems = items.filter((k) => k.status === ApiKeyStatus.ACTIVE);
    const count = activeItems.length;
    const label = count === 1 ? 'key' : 'keys';

    return {
        title: 'Revoke API keys',
        message:
            "Revoked keys stop working immediately and can't be restored. Any service still using them will lose access.",
        caution: `<details open><summary>You are about to revoke <strong>${count}</strong> active ${label}.</summary>${keyListHtml(activeItems)}</details>`,
        type: 'danger',
        confirmText: `Revoke ${count} ${label}`,
        cancelText: 'Cancel',
    };
}

export function getBulkDeleteConfirmationData(items: BulkApiKeyItem[]): ConfirmationDialogData {
    const count = items.length;
    const label = count === 1 ? 'key' : 'keys';
    const hasActiveKeys = items.some((k) => k.status === ApiKeyStatus.ACTIVE);

    const message = hasActiveKeys
        ? "These keys are still active. Live integrations will break immediately and this can't be undone."
        : "Deleted keys can't be restored.";

    return {
        title: 'Delete keys',
        message,
        caution: `<details open><summary>You are about to delete <strong>${count}</strong> ${label}.</summary>${keyListHtml(items)}</details>`,
        type: 'danger',
        confirmText: `Delete ${count} ${label}`,
        cancelText: 'Cancel',
    };
}
