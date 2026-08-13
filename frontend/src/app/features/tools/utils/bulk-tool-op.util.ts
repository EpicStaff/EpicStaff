import { HttpErrorResponse } from '@angular/common/http';
import { DestroyRef, WritableSignal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ConfirmationDialogData, ConfirmationDialogService } from '@shared/components';
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
        /** Scope word rendered in the success toast (e.g. 'unused', 'selected'). */
        scopeLabel: 'unused' | 'selected';
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
                        opts.toast.success(`Deleted ${response.deleted} ${opts.scopeLabel} ${opts.entityLabel}(s).`);
                    },
                    error: (err: HttpErrorResponse) => {
                        opts.toast.error(
                            err.error?.message || `Failed to delete ${opts.scopeLabel} ${opts.entityLabel}s.`
                        );
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
    }
): void {
    if (filteredIds.length === 0) return;
    opts.getBulkUsage(filteredIds)
        .pipe(takeUntilDestroyed(opts.destroyRef))
        .subscribe({
            next: (items) => {
                const unusedIds = items
                    .filter((i) => i.projects_count === 0 && i.staff_count === 0 && !i.is_built_in)
                    .map((i) => i.id);
                if (unusedIds.length === 0) {
                    opts.toast.info(`No unused ${opts.entityLabel}s to delete.`);
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
                    scopeLabel: 'unused',
                    dialogData: buildUnusedDeleteDialog(unusedIds.length, opts.entityLabelPlural),
                });
            },
            error: (err: HttpErrorResponse) => {
                opts.toast.error(err.error?.message || 'Failed to load usage data.');
            },
        });
}

// Delete-confirmation dialog builders
function pluralise(count: number, singular: string, plural: string): string {
    return count === 1 ? singular : plural;
}

function escapeHtml(value: string): string {
    return value
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

/**
 * Bulk delete of tools that have no agent/project usages.
 */
export function buildUnusedDeleteDialog(count: number, entityLabelPlural: string): ConfirmationDialogData {
    const title = count === 1 ? 'Deleting Tool?' : 'Deleting Tools?';
    return {
        title,
        message:
            `You are about to permanently delete <strong>${count} ${entityLabelPlural}</strong> ` +
            `that are not currently connected to any agents or projects. This action cannot be undone.`,
        confirmText: 'Delete',
        cancelText: 'Cancel',
        type: 'danger',
    };
}

/**
 * Single-tool delete with a "Caution" block that summarises
 * the agent + project dependencies that will be broken.
 */
export function buildSingleDeleteWithUsageDialog(
    toolName: string,
    staffCount: number,
    projectsCount: number
): ConfirmationDialogData {
    const safeName = escapeHtml(toolName);
    return {
        title: 'Delete Tool?',
        message:
            `You are about to permanently delete <strong>${safeName}</strong>. ` +
            `This action cannot be undone and will break existing dependencies.`,
        cautionTitle: 'Caution',
        caution:
            `This tool is currently connected to <strong>${staffCount} ${pluralise(staffCount, 'agent', 'agents')}</strong> ` +
            `and <strong>${projectsCount} ${pluralise(projectsCount, 'project', 'projects')}</strong>. ` +
            `If deleted, it will be removed from all of these workspaces.`,
        confirmText: 'Delete',
        cancelText: 'Cancel',
        type: 'danger',
    };
}

/**
 * Bulk selected delete when at least one tool has usages.
 * Tools are sorted by total usage descending so the heaviest dependencies
 * surface first in the collapsible list.
 */
export function buildBulkSelectedDeleteDialog(
    tools: { id: number; name: string; staffCount: number; projectsCount: number }[]
): ConfirmationDialogData {
    const count = tools.length;
    const sorted = [...tools].sort((a, b) => b.staffCount + b.projectsCount - (a.staffCount + a.projectsCount));
    const listItems = sorted
        .map((t) => {
            const safeName = escapeHtml(t.name);
            return (
                `<li><strong>${safeName}</strong> is connected to ` +
                `<strong>${t.staffCount} ${pluralise(t.staffCount, 'agent', 'agents')}</strong> and ` +
                `<strong>${t.projectsCount} ${pluralise(t.projectsCount, 'project', 'projects')}</strong>.</li>`
            );
        })
        .join('');

    return {
        title: 'Delete Tools?',
        message:
            'This action cannot be undone and will break existing dependencies ' +
            'across multiple agents and projects.',
        caution:
            `<details open><summary>You are about to permanently delete <strong>${count} tools</strong>.</summary>` +
            `<ul>${listItems}</ul></details>`,
        confirmText: 'Delete',
        cancelText: 'Cancel',
        type: 'danger',
    };
}
