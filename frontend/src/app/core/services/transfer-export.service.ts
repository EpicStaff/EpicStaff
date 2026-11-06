import { inject, Injectable } from '@angular/core';
import { groupExcludedExportItems, showExportExclusionWarning } from '@shared/utils';
import { defer, EMPTY, Observable } from 'rxjs';
import { catchError, finalize, map, switchMap, tap } from 'rxjs/operators';

import { ToastService } from '../../services/notifications';
import { TransferJob, TransferJobCreated } from '../models/transfer-job.model';
import { describeTransferError, TRANSFER_JOB_MAX_WAIT_MS, TransferJobsService } from './transfer-jobs.service';

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

    /** Emits the finished job once its download has started. */
    exportFlows(ids: number[], includeKnowledge: boolean): Observable<TransferJob> {
        return this.exportAndDownload(() => this.transferJobs.startFlowExport(ids, includeKnowledge));
    }

    /** Emits the finished job once its download has started. */
    exportCollections(ids: number[]): Observable<TransferJob> {
        return this.exportAndDownload(() => this.transferJobs.startCollectionExport(ids));
    }

    private exportAndDownload(startJob: () => Observable<TransferJobCreated>): Observable<TransferJob> {
        return defer(() => {
            const progressToastId = this.toastService.show(EXPORT_PROGRESS_MESSAGE, 'info', TRANSFER_JOB_MAX_WAIT_MS);
            return startJob().pipe(
                switchMap(({ job_id }) => this.transferJobs.waitForJob(job_id)),
                switchMap((job) => this.transferJobs.downloadExport(job).pipe(map(() => job))),
                tap((job) => {
                    const excluded = job.kind === 'export' ? (job.result?.excluded ?? []) : [];
                    showExportExclusionWarning(this.toastService, groupExcludedExportItems(excluded));
                }),
                catchError((error: unknown) => {
                    this.toastService.error(describeTransferError(error, 'Failed to export. Please try again.'));
                    return EMPTY;
                }),
                finalize(() => this.toastService.remove(progressToastId))
            );
        });
    }
}
