import { HttpErrorResponse } from '@angular/common/http';
import { DestroyRef, WritableSignal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ConfirmationDialogData, ConfirmationDialogService } from '@shared/components';
import { escapeHtml, movedToRecycleBinMessage, pluralize, recycleBinNotice } from '@shared/utils';
import { Observable } from 'rxjs';

import { ToastService } from '../../../services/notifications';
import { BulkDeleteToolsResponse, GetBulkToolUsageItem } from '../models/tool-config.model';
import { ToolsViewStorageService } from '../services/tools-view-storage.service';
import { partitionSettled, settleAll } from './settle-all';

/**
 * Shared skeleton for parallel bulk operations that fan out to per-item
 * requests. Uses `settleAll` (so one failing item doesn't cancel the rest),
 * partitions the results, then reports partial success/failure via toasts.
 * Callers plug in the mutation on the local list via `applySuccess`.
 */
export function runSettledBulk<T>(
    requests: Observable<T>[],
    opts: {
        destroyRef: DestroyRef;
        toast: ToastService;
        viewState: ToolsViewStorageService;
        applySuccess: (items: T[]) => void;
        successMessage: (count: number) => string;
        failureMessage: (count: number) => string;
        /** Called when at least one request fails, so callers can refetch the list to stay in sync. */
        onError?: () => void;
    }
): void {
    if (requests.length === 0) return;
    settleAll(requests)
        .pipe(takeUntilDestroyed(opts.destroyRef))
        .subscribe((results) => {
            const { successes, failures } = partitionSettled(results);
            if (successes.length > 0) {
                opts.applySuccess(successes);
                opts.viewState.clearSelection();
                opts.toast.success(opts.successMessage(successes.length));
            }
            if (failures.length > 0) {
                opts.toast.error(opts.failureMessage(failures.length));
                opts.onError?.();
            }
        });
}

/**
 * Confirms deletion with the user (using caller-provided dialog data), then
 * hits the caller-supplied `bulkDelete` endpoint (which takes an id array in
 * a single request), removes the ids from the local list signal, clears
 * selection, and toasts.
 */
export function runBulkDeleteWithConfirm<T extends { id: number }>(
    ids: number[],
    opts: {
        destroyRef: DestroyRef;
        toast: ToastService;
        confirmation: ConfirmationDialogService;
        viewState: ToolsViewStorageService;
        allTools: WritableSignal<T[]>;
        bulkDelete: (ids: number[]) => Observable<BulkDeleteToolsResponse>;
        /** Pre-built dialog data (title/message/caution). */
        dialogData: ConfirmationDialogData;
        /** Human-readable noun used in the toast messages (e.g. 'custom tool', 'MCP tool'). */
        entityLabel: string;
        /** Plural of `entityLabel` (e.g. 'custom tools', 'MCP tools'). */
        entityLabelPlural: string;
        /** Scope word rendered in the failure toast (e.g. 'unused', 'selected'). */
        scopeLabel: 'unused' | 'selected';
        /** Called when the delete request fails, so callers can refetch the list to stay in sync. */
        onError?: () => void;
    }
): void {
    if (ids.length === 0) return;
    opts.confirmation
        .confirm(opts.dialogData)
        .pipe(takeUntilDestroyed(opts.destroyRef))
        .subscribe((result) => {
            if (result !== true) return;
            opts.bulkDelete(ids)
                .pipe(takeUntilDestroyed(opts.destroyRef))
                .subscribe({
                    next: (response) => {
                        const idSet = new Set(ids);
                        opts.allTools.update((list) => list.filter((t) => !idSet.has(t.id)));
                        opts.viewState.clearSelection();
                        opts.toast.success(
                            movedToRecycleBinMessage(response.deleted, opts.entityLabel, opts.entityLabelPlural)
                        );
                    },
                    error: (err: HttpErrorResponse) => {
                        opts.toast.error(
                            err.error?.message || `Failed to delete ${opts.scopeLabel} ${opts.entityLabel}s.`
                        );
                        opts.onError?.();
                    },
                });
        });
}

/**
 * Full "delete all unused" pipeline: fetch bulk usage for the caller-provided
 * ids, keep only ids with zero project + zero staff usage that are not
 * built-in, then run {@link runBulkDeleteWithConfirm} on the result. Emits an
 * info toast when nothing is unused.
 */
export function runDeleteUnused<T extends { id: number }>(
    filteredIds: number[],
    opts: {
        destroyRef: DestroyRef;
        toast: ToastService;
        confirmation: ConfirmationDialogService;
        viewState: ToolsViewStorageService;
        allTools: WritableSignal<T[]>;
        getBulkUsage: (ids: number[]) => Observable<GetBulkToolUsageItem[]>;
        bulkDelete: (ids: number[]) => Observable<BulkDeleteToolsResponse>;
        /** Human-readable noun used in the toasts (e.g. 'custom tool', 'MCP tool'). */
        entityLabel: string;
        /** Plural noun used in the confirm dialog message (e.g. 'custom tools', 'MCP tools'). */
        entityLabelPlural: string;
        /** Days a deleted tool stays in the recycle bin; `null` when unknown. */
        retentionDays: number | null;
        /** Called when the usage lookup or delete request fails, so callers can refetch the list. */
        onError?: () => void;
    }
): void {
    if (filteredIds.length === 0) return;
    opts.getBulkUsage(filteredIds)
        .pipe(takeUntilDestroyed(opts.destroyRef))
        .subscribe({
            next: (items) => {
                const unusedIds = items
                    .filter(
                        (i) =>
                            i.agent_surface_count === 0 &&
                            i.shared_surface_count === 0 &&
                            i.inline_surface_count === 0 &&
                            !i.is_built_in
                    )
                    .map((i) => i.id);
                if (unusedIds.length === 0) {
                    opts.toast.success(`No unused ${opts.entityLabel}s to delete.`);
                    return;
                }
                runBulkDeleteWithConfirm(unusedIds, {
                    destroyRef: opts.destroyRef,
                    toast: opts.toast,
                    confirmation: opts.confirmation,
                    viewState: opts.viewState,
                    allTools: opts.allTools,
                    bulkDelete: opts.bulkDelete,
                    entityLabel: opts.entityLabel,
                    entityLabelPlural: opts.entityLabelPlural,
                    scopeLabel: 'unused',
                    dialogData: buildUnusedDeleteDialog(
                        unusedIds.length,
                        opts.entityLabel,
                        opts.entityLabelPlural,
                        opts.retentionDays
                    ),
                    onError: opts.onError,
                });
            },
            error: (err: HttpErrorResponse) => {
                opts.toast.error(err.error?.message || 'Failed to load usage data.');
                opts.onError?.();
            },
        });
}

// Delete-confirmation dialog builders

interface ToolUsageCounts {
    agentSurfaceCount: number;
    sharedSurfaceCount: number;
    inlineSurfaceCount: number;
}

function totalUsage(tool: ToolUsageCounts): number {
    return tool.agentSurfaceCount + tool.sharedSurfaceCount + tool.inlineSurfaceCount;
}

/** `<strong>1 agent tool surface</strong>, <strong>0 shared tool surfaces</strong>, and <strong>2 inline usages</strong>` */
function usageCounts(tool: ToolUsageCounts): string {
    return (
        `<strong>${pluralize(tool.agentSurfaceCount, 'agent tool surface', 'agent tool surfaces')}</strong>, ` +
        `<strong>${pluralize(tool.sharedSurfaceCount, 'shared tool surface', 'shared tool surfaces')}</strong>, ` +
        `and <strong>${pluralize(tool.inlineSurfaceCount, 'inline usage', 'inline usages')}</strong>`
    );
}

/**
 * Bulk delete of tools that have no agent/project usages.
 */
export function buildUnusedDeleteDialog(
    count: number,
    entityLabel: string,
    entityLabelPlural: string,
    retentionDays: number | null
): ConfirmationDialogData {
    return {
        title: count === 1 ? 'Delete unused tool?' : 'Delete unused tools?',
        message:
            `You are about to delete <strong>${pluralize(count, entityLabel, entityLabelPlural)}</strong> ` +
            `that aren't connected to any agents or projects. ${recycleBinNotice(retentionDays, count)}`,
        confirmText: 'Delete',
        cancelText: 'Cancel',
        type: 'danger',
    };
}

/**
 * Single-tool delete with a "Caution" block that summarises
 * the surface dependencies (agent / shared / inline) that will be broken.
 */
export function buildSingleDeleteWithUsageDialog(
    toolName: string,
    agentSurfaceCount: number,
    sharedSurfaceCount: number,
    inlineCount: number,
    retentionDays: number | null
): ConfirmationDialogData {
    const safeName = escapeHtml(toolName);
    const counts = usageCounts({ agentSurfaceCount, sharedSurfaceCount, inlineSurfaceCount: inlineCount });
    return {
        title: 'Delete Tool?',
        message: `You are about to delete <strong>${safeName}</strong>. ${recycleBinNotice(retentionDays)}`,
        cautionTitle: 'Caution',
        caution:
            `This tool is currently connected to ${counts}. ` +
            `If deleted, it's removed from all of these surfaces, and restoring it won't reconnect them.`,
        confirmText: 'Delete',
        cancelText: 'Cancel',
        type: 'danger',
    };
}

/**
 * Bulk selected delete. Only the tools that are used get the dependency warning and a usage line,
 * sorted by total usage descending so the heaviest dependencies come first in the collapsible list.
 * A selection of unused tools gets a plain confirmation.
 */
export function buildBulkSelectedDeleteDialog(
    tools: ({ id: number; name: string } & ToolUsageCounts)[],
    retentionDays: number | null
): ConfirmationDialogData {
    const count = tools.length;
    const deleteSentence =
        `You are about to delete <strong>${pluralize(count, 'tool', 'tools')}</strong>. ` +
        recycleBinNotice(retentionDays, count);
    const dialog: ConfirmationDialogData = {
        title: count === 1 ? 'Delete Tool?' : 'Delete Tools?',
        message: deleteSentence,
        confirmText: 'Delete',
        cancelText: 'Cancel',
        type: 'danger',
    };

    const used = tools.filter((tool) => totalUsage(tool) > 0).sort((a, b) => totalUsage(b) - totalUsage(a));
    if (used.length === 0) return dialog;

    const listItems = used
        .map((tool) => `<li><strong>${escapeHtml(tool.name)}</strong> is connected to ${usageCounts(tool)}.</li>`)
        .join('');
    const usedNote = used.length < count ? ` ${used.length} of them ${used.length === 1 ? 'is' : 'are'} in use.` : '';
    return {
        ...dialog,
        message:
            'This breaks existing dependencies across agent, shared, and inline tool surfaces. ' +
            `Restoring ${count === 1 ? 'the tool' : 'the tools'} won't reconnect them.`,
        caution: `<details open><summary>${deleteSentence}${usedNote}</summary><ul>${listItems}</ul></details>`,
    };
}
