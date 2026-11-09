import { DatePipe } from '@angular/common';
import { afterRenderEffect, Component, computed, ElementRef, inject, input, OnInit, viewChildren } from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';
import { AppSvgIconComponent, ButtonComponent, ConfirmationDialogService } from '@shared/components';
import { TooltipOnOverflowDirective } from '@shared/directives';

import {
    isDownloadableExport,
    isUnfinishedTransferJob,
    TRANSFER_JOB_ENTITY_LABELS,
    TransferJob,
    transferJobName,
    TransferJobStatus,
} from '../../../../core/models/transfer-job.model';
import { TransferJobsStoreService } from '../../../../core/services/transfer-jobs-store.service';

/** `popover`: a panel of its own, with a heading; `inline`: under its row in the sidebar drawer. */
export type TransferJobsPanelVariant = 'popover' | 'inline';

export const RUNNING_JOB_CLEAR_HINT = 'A running job cannot be cleared. Wait for it to finish.';
const CLEAR_HINT = 'Clear';
/** Why Clear all does nothing: the jobs are not known yet, the list is empty, or every job in it is running. */
const LOADING_CLEAR_ALL_HINT = 'Loading the jobs…';
const LOAD_FAILED_CLEAR_ALL_HINT = 'The jobs could not be loaded.';
const NO_JOBS_CLEAR_ALL_HINT = 'There are no jobs to clear.';
const ONLY_RUNNING_JOBS_CLEAR_ALL_HINT = 'Running jobs cannot be cleared. Wait for them to finish.';

const STATUS_LABELS: Record<TransferJobStatus, string> = {
    queued: 'Queued',
    running: 'Running',
    completed: 'Completed',
    failed: 'Failed',
};

interface TransferJobRow {
    job: TransferJob;
    name: string;
    /** What the job does, and with what: "Export · Flows". */
    description: string;
    status: TransferJobStatus;
    statusLabel: string;
    inProgress: boolean;
    errorMessage: string | null;
    canDownload: boolean;
    /** Until when the archive of a downloadable export is kept. */
    availableUntil: string | null;
    canClear: boolean;
    /** Why Clear does nothing, or what it does. */
    clearHint: string;
}

/** The user's exports and imports: how each one stands, the archive of a ready export, and a way to clear them. */
@Component({
    selector: 'app-transfer-jobs-panel',
    imports: [AppSvgIconComponent, ButtonComponent, DatePipe, MatTooltip, TooltipOnOverflowDirective],
    templateUrl: './transfer-jobs-panel.component.html',
    styleUrl: './transfer-jobs-panel.component.scss',
    host: {
        '[class.transfer-jobs-panel--popover]': "variant() === 'popover'",
        '[class.transfer-jobs-panel--inline]': "variant() === 'inline'",
    },
})
export class TransferJobsPanelComponent implements OnInit {
    readonly variant = input<TransferJobsPanelVariant>('popover');

    private readonly rowElements = viewChildren<ElementRef<HTMLElement>>('jobRow');

    protected readonly isLoading = inject(TransferJobsStoreService).isLoading;
    protected readonly loadFailed = inject(TransferJobsStoreService).loadFailed;
    protected readonly isLoadingMore = inject(TransferJobsStoreService).isLoadingMore;
    protected readonly loadMoreFailed = inject(TransferJobsStoreService).loadMoreFailed;
    protected readonly canClearAll = inject(TransferJobsStoreService).hasClearableJobs;
    protected readonly isClearingAll = inject(TransferJobsStoreService).isClearingAll;
    /** The button stays while a page loads or failed to, so the focus it holds is not lost. */
    protected readonly showsMoreButton = computed(
        () => this.store.remainingCount() > 0 || this.isLoadingMore() || this.loadMoreFailed()
    );
    protected readonly moreLabel = computed(() => {
        if (this.isLoadingMore()) return 'Loading…';
        if (this.loadMoreFailed()) return 'Try again';
        return `Show more (${this.store.remainingCount()} left)`;
    });
    protected readonly rows = computed<TransferJobRow[]>(() => {
        const clearing = this.store.clearingIds();
        return this.store.jobs().map((job) => this.toRow(job, clearing.has(job.id)));
    });
    /** Why Clear all does nothing; nothing while it can clear, as its label says what it does. */
    protected readonly clearAllHint = computed(() => {
        if (this.canClearAll()) return undefined;
        if (this.isLoading()) return LOADING_CLEAR_ALL_HINT;
        if (this.loadFailed()) return LOAD_FAILED_CLEAR_ALL_HINT;
        return this.store.jobs().length > 0 ? ONLY_RUNNING_JOBS_CLEAR_ALL_HINT : NO_JOBS_CLEAR_ALL_HINT;
    });

    /**
     * Once the last page has come, the button the focus was on is gone: the focus goes to the first job it brought.
     * While more remain the button stays, and keeps the focus.
     */
    private readonly focusFirstLoadedRow = afterRenderEffect(() => {
        const isLoadingMore = this.isLoadingMore();
        const showsMoreButton = this.showsMoreButton();
        const rowElements = this.rowElements();
        if (this.firstNewRowIndex === null || isLoadingMore) return;
        const index = this.firstNewRowIndex;
        this.firstNewRowIndex = null;
        if (!showsMoreButton) {
            rowElements[index]?.nativeElement.focus();
        }
    });

    protected readonly heading = 'Exports and imports';

    private readonly store = inject(TransferJobsStoreService);
    private readonly confirmationDialog = inject(ConfirmationDialogService);
    /** Where the jobs a "show more" asked for start in the list. */
    private firstNewRowIndex: number | null = null;

    // Opened to see how the jobs stand: what another tab started, or what has expired meanwhile, shows too.
    ngOnInit(): void {
        this.store.reload();
    }

    protected reload(): void {
        this.store.reload();
    }

    protected showMore(): void {
        this.firstNewRowIndex = this.rows().length;
        this.store.loadMore();
    }

    protected download(job: TransferJob): void {
        if (isDownloadableExport(job)) {
            this.store.download(job);
        }
    }

    protected clear(row: TransferJobRow): void {
        if (row.canClear) {
            this.store.clearJob(row.job);
        }
    }

    /**
     * Not ended with this panel: the sidebar can close the list holding it while the dialog is up (the window resized
     * the sidebar), and the answer still counts. The stream ends with the dialog.
     */
    protected clearAll(): void {
        if (!this.canClearAll() || this.isClearingAll()) {
            return;
        }
        this.confirmationDialog
            .confirm({
                title: 'Clear all jobs?',
                message:
                    "Removes all your export and import jobs except running ones. Finished exports can't be downloaded " +
                    'afterwards.',
                confirmText: 'Clear all',
                cancelText: 'Cancel',
                type: 'danger',
            })
            .subscribe((result) => {
                if (result === true) {
                    this.store.clearAll();
                }
            });
    }

    private toRow(job: TransferJob, isClearing: boolean): TransferJobRow {
        const canDownload = isDownloadableExport(job);
        const isRunning = job.status === 'running';
        return {
            job,
            name: transferJobName(job),
            description: `${job.kind === 'export' ? 'Export' : 'Import'} · ${TRANSFER_JOB_ENTITY_LABELS[job.main_entity] ?? job.main_entity}`,
            status: job.status,
            statusLabel: STATUS_LABELS[job.status],
            inProgress: isUnfinishedTransferJob(job),
            errorMessage: job.error?.message || null,
            canDownload,
            availableUntil: canDownload ? job.expires_at : null,
            canClear: !isRunning && !isClearing,
            clearHint: isRunning ? RUNNING_JOB_CLEAR_HINT : CLEAR_HINT,
        };
    }
}
