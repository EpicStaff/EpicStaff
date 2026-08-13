import { HttpErrorResponse } from '@angular/common/http';
import { DestroyRef, WritableSignal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ConfirmationDialogService } from '@shared/components';
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
 * Confirms deletion with the user, then hits the caller-supplied `bulkDelete`
 * endpoint (which takes an id array in a single request), removes the ids
 * from the local list signal, clears selection, and toasts.
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
        /** Human-readable noun used in the confirm/toast messages (e.g. 'custom tool', 'MCP tool'). */
        entityLabel: string;
        /** Scope word rendered in the success toast (e.g. 'unused', 'selected'). */
        scopeLabel: 'unused' | 'selected';
    }
): void {
    if (ids.length === 0) return;
    opts.confirmation
        .confirm({
            title: 'Confirm Deletion',
            message: `Are you sure you want to delete <strong>${ids.length}</strong> ${opts.entityLabel}(s)? <br> This action cannot be undone.`,
            confirmText: 'Delete',
            cancelText: 'Cancel',
            type: 'danger',
        })
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
                });
            },
            error: (err: HttpErrorResponse) => {
                opts.toast.error(err.error?.message || 'Failed to load usage data.');
            },
        });
}
