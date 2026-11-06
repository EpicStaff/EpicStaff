import { computed, inject, Injectable, signal } from '@angular/core';
import { groupExcludedExportItems, showExportExclusionWarning, withProgressToast } from '@shared/utils';
import { defer, EMPTY, Observable } from 'rxjs';
import { catchError, finalize, map, switchMap, tap } from 'rxjs/operators';

import { ToastService } from '../../services/notifications';
import { TransferJob } from '../models/transfer-job.model';
import {
    describeTransferError,
    StartedTransferJob,
    TRANSFER_JOB_MAX_WAIT_MS,
    TransferJobsService,
} from './transfer-jobs.service';

export const EXPORT_PROGRESS_MESSAGE = 'Preparing export…';

/**
 * Exports as a background job: shows the progress, downloads the archive once it is ready and warns
 * about what was left out. A failure is shown as a toast and the observable completes without emitting.
 *
 * Not tied to the page that started it: an export the user started still downloads after they leave.
 */
@Injectable({
    providedIn: 'root',
})
export class TransferExportService {
    private readonly transferJobs = inject(TransferJobsService);
    private readonly toastService = inject(ToastService);

    /** How many unfinished exports each collection is in. Kept here, as an export outlives the page. */
    private readonly collectionExportCounts = signal<ReadonlyMap<number, number>>(new Map());
    /** Collections in an export that has not finished yet. */
    readonly exportingCollectionIds = computed<ReadonlySet<number>>(
        () => new Set(this.collectionExportCounts().keys())
    );

    /** Emits the finished job once its download has started. */
    exportFlows(ids: number[], includeKnowledge: boolean): Observable<TransferJob> {
        return this.exportAndDownload(this.transferJobs.startFlowExport(ids, includeKnowledge));
    }

    /**
     * Emits the finished job once its download has started. Completes at once, starting nothing, when every one
     * of the collections is already being exported: a second click on Export would only repeat the job.
     */
    exportCollections(ids: number[]): Observable<TransferJob> {
        return defer(() => {
            const exporting = this.exportingCollectionIds();
            if (ids.every((id) => exporting.has(id))) {
                return EMPTY;
            }
            this.countCollectionExports(ids, 1);
            return this.exportAndDownload(this.transferJobs.startCollectionExport(ids)).pipe(
                finalize(() => this.countCollectionExports(ids, -1))
            );
        });
    }

    private exportAndDownload(start: Observable<StartedTransferJob>): Observable<TransferJob> {
        return start.pipe(
            switchMap((started) =>
                this.transferJobs
                    .waitForJob(started)
                    .pipe(
                        switchMap((job) =>
                            this.transferJobs.downloadExport(started, job.file_name).pipe(map(() => job))
                        )
                    )
            ),
            tap((job) => {
                const excluded = job.kind === 'export' ? (job.result?.excluded ?? []) : [];
                showExportExclusionWarning(this.toastService, groupExcludedExportItems(excluded));
            }),
            catchError((error: unknown) => {
                this.toastService.error(describeTransferError(error, 'Failed to export. Please try again.'));
                return EMPTY;
            }),
            withProgressToast(this.toastService, EXPORT_PROGRESS_MESSAGE, TRANSFER_JOB_MAX_WAIT_MS)
        );
    }

    private countCollectionExports(ids: number[], change: 1 | -1): void {
        const counts = new Map(this.collectionExportCounts());
        for (const id of ids) {
            const count = (counts.get(id) ?? 0) + change;
            if (count > 0) {
                counts.set(id, count);
            } else {
                counts.delete(id);
            }
        }
        this.collectionExportCounts.set(counts);
    }
}
