import { HttpErrorResponse } from '@angular/common/http';
import { ConfirmationDialogData } from '@shared/components';
import { escapeHtml } from '@shared/utils';

import { RECYCLE_BIN_LINK_KEEPING_SOURCES } from '../constants/recycle-bin-sources.constants';
import {
    RecycleBinFailure,
    RecycleBinItem,
    RecycleBinPurgeResult,
    RecycleBinRestoreOutcome,
    RecycleBinRestoreResult,
    RecycleBinTabDefinition,
} from '../models/recycle-bin.model';

export type RecycleBinAction = 'restore' | 'delete';

// The toasts below are plain text: ToastService renders text, not HTML.

/**
 * Restoring brings the item back. A secret, voice channel or webhook trigger kept its links, so what used it
 * works again; any other item comes back without the links it had (they were removed for good).
 */
export function restoreSuccessMessage(outcome: RecycleBinRestoreOutcome): string {
    const restored =
        outcome.renamedFrom === null
            ? `"${outcome.name}" restored.`
            : `"${outcome.renamedFrom}" restored as "${outcome.name}", because that name was taken.`;
    return `${restored} ${linksNote([outcome], 'it', 'Its')}`;
}

/** What happened to the links: connected again when every item kept them, otherwise not restored. */
function linksNote(outcomes: readonly RecycleBinRestoreOutcome[], object: string, possessive: string): string {
    return outcomes.every((outcome) => RECYCLE_BIN_LINK_KEEPING_SOURCES.has(outcome.source))
        ? `Everything that used ${object} is connected again.`
        : `${possessive} links to other items aren't restored.`;
}

/**
 * Toast text for a failed restore or permanent delete. `null` for a 403: the forbidden
 * interceptor already shows the server's message and reloads the permissions.
 */
export function recycleBinActionErrorMessage(
    error: HttpErrorResponse,
    action: RecycleBinAction,
    itemName: string
): string | null {
    const fallback = `Couldn't ${action} "${itemName}". Please try again.`;
    switch (error.status) {
        case 403:
            return null;
        case 404:
            return 'This item is no longer in the recycle bin.';
        default:
            return fallback;
    }
}

/** Like recycleBinActionErrorMessage, for an action on several items or a whole tab. */
export function bulkActionErrorMessage(error: HttpErrorResponse, action: RecycleBinAction): string | null {
    switch (error.status) {
        case 403:
            return null;
        // The backend checks every id first and changes nothing when one is missing.
        case 404:
            return 'Some of these items are no longer in the recycle bin. The list has been refreshed.';
        default:
            return `Couldn't ${action} these items. Please try again.`;
    }
}

// The dialog renders `title` as text and `message` with [innerHTML], so only the message escapes the name.

/** The permanent-delete dialog of one item: a plain confirmation (only emptying the bin asks to type a phrase). */
export function purgeConfirmationDialog(item: RecycleBinItem): ConfirmationDialogData {
    return dangerDialog('Delete permanently?', purgeConfirmationMessage(item));
}

export function purgeConfirmationMessage(item: RecycleBinItem): string {
    // Storage folder names end in "/". Purging a folder also purges what was deleted together with it.
    const isFolder = item.source === 'storage' && item.name.endsWith('/');
    const folderNote = isFolder ? ' Everything that was deleted with it goes too.' : '';
    return `<strong>${escapeHtml(item.name)}</strong> will be deleted for good.${folderNote} You can't undo this.`;
}

// Bulk actions

/** How many names a dialog or toast lists before "…and N more". */
const LISTED_NAMES = 3;

/** `"a", "b", "c" and 4 more` (plain text) or with each name in <strong> (dialog HTML). */
function listNames(names: readonly string[], total: number, html: boolean): string {
    const shown = names
        .slice(0, LISTED_NAMES)
        .map((name) => (html ? `<strong>${escapeHtml(name)}</strong>` : `"${name}"`));
    const rest = total - shown.length;
    if (rest <= 0) {
        return shown.length > 1 ? `${shown.slice(0, -1).join(', ')} and ${shown.at(-1)}` : (shown[0] ?? '');
    }
    return `${shown.join(', ')} and ${rest} more`;
}

function itemCount(count: number): string {
    return `${count} ${count === 1 ? 'item' : 'items'}`;
}

/** The phrase "Empty recycle bin" asks to type: the one action here that deletes things the user didn't pick. */
export const EMPTY_RECYCLE_BIN_PHRASE = 'empty-recycle-bin';

export function purgeSelectedConfirmationDialog(names: readonly string[]): ConfirmationDialogData {
    return dangerDialog(
        'Delete permanently?',
        `${listNames(names, names.length, true)} will be deleted for good. You can't undo this.`
    );
}

/** Empties every tab the user may delete on; `tabs` are those tabs. */
export function emptyRecycleBinConfirmationDialog(tabs: readonly RecycleBinTabDefinition[]): ConfirmationDialogData {
    const labels = tabs.map((tab) => `<strong>${escapeHtml(tab.label)}</strong>`).join(', ');
    return dangerDialog(
        'Empty the recycle bin?',
        `Everything on these tabs will be deleted for good: ${labels}. You can't undo this.`,
        EMPTY_RECYCLE_BIN_PHRASE
    );
}

/** `phrase`, when given, must be typed to confirm: a frontend-only safeguard, the purge endpoints take none. */
function dangerDialog(title: string, message: string, phrase?: string): ConfirmationDialogData {
    return {
        title,
        message,
        type: 'danger',
        confirmText: 'Delete permanently',
        cancelText: 'Cancel',
        ...(phrase ? { verification: { phrase } } : {}),
    };
}

/**
 * Success toast of a restore: the single-item wording for one item, else totals with the renames.
 * `null` when nothing was restored.
 */
export function restoreResultMessage(result: RecycleBinRestoreResult): string | null {
    const { restored } = result;
    if (restored.length === 0) return null;
    if (restored.length === 1) return restoreSuccessMessage(restored[0]);
    const renamed = restored.filter((outcome) => outcome.renamedFrom !== null);
    const renames = renamed.slice(0, LISTED_NAMES).map((outcome) => `${outcome.renamedFrom} → ${outcome.name}`);
    const moreRenames = renamed.length - renames.length;
    const renameNote =
        renamed.length === 0
            ? ''
            : `, ${renamed.length} renamed: ${renames.join(', ')}${moreRenames > 0 ? ` and ${moreRenames} more` : ''}`;
    return `${restored.length} restored${renameNote}. ${linksNote(restored, 'them', 'Their')}`;
}

/** Success toast of a permanent delete; `itemName` for a single row. `null` when nothing was deleted. */
export function purgeResultMessage(result: RecycleBinPurgeResult, itemName?: string): string | null {
    if (result.purgedCount === 0) return null;
    if (result.purgedCount === 1 && itemName !== undefined) return `"${itemName}" deleted permanently.`;
    return `${itemCount(result.purgedCount)} deleted permanently.`;
}

/** Error toast for the items a bulk action skipped (the others went ahead). `null` when none failed. */
export function failedItemsMessage(action: RecycleBinAction, failed: readonly RecycleBinFailure[]): string | null {
    if (failed.length === 0) return null;
    const shown = failed.slice(0, LISTED_NAMES).map((failure) => `"${failure.name}": ${failure.message}`);
    const rest = failed.length - shown.length;
    return `Couldn't ${action} ${itemCount(failed.length)}. ${shown.join(' ')}${rest > 0 ? ` …and ${rest} more.` : ''}`;
}
