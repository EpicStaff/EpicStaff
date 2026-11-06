import { inject, Injectable } from '@angular/core';
import { groupExcludedExportItems, showExportExclusionWarning } from '@shared/utils';
import { defer, EMPTY, Observable } from 'rxjs';
import { catchError, finalize, map, switchMap, tap } from 'rxjs/operators';

import { TransferJob } from '../../../core/models/transfer-job.model';
import {
    describeTransferError,
    TRANSFER_JOB_MAX_WAIT_MS,
    TransferJobsService,
} from '../../../core/services/transfer-jobs.service';
import { ToastService } from '../../../services/notifications';

export const EXPORT_PROGRESS_MESSAGE = 'Preparing export…';

/**
 * Exports flows as a background job: shows the progress, downloads the archive once it is ready and warns
 * about what was left out. A failure is shown as a toast and the observable completes without emitting.
 */
@Injectable({
    providedIn: 'root',
})
export class FlowExportService {
    private readonly transferJobs = inject(TransferJobsService);
    private readonly toastService = inject(ToastService);

    /** Emits the finished job once its download has started. */
    exportFlows(ids: number[], includeKnowledge: boolean): Observable<TransferJob> {
        return defer(() => {
            const progressToastId = this.toastService.show(EXPORT_PROGRESS_MESSAGE, 'info', TRANSFER_JOB_MAX_WAIT_MS);
            return this.transferJobs.startFlowExport(ids, includeKnowledge).pipe(
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
