import { HttpClient, HttpErrorResponse, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { extractHttpErrorMessage } from '@shared/utils';
import { Observable, throwError, timer } from 'rxjs';
import { exhaustMap, first, map, timeout } from 'rxjs/operators';

import { ConfigService } from '../../services/config';
import { ImportFlowRequestOptions } from '../models/import-result.model';
import {
    TransferImportTarget,
    TransferJob,
    TransferJobCreated,
    TransferJobDownloadTicket,
} from '../models/transfer-job.model';

export const TRANSFER_JOB_POLL_INTERVAL_MS = 2_000;
export const TRANSFER_JOB_MAX_WAIT_MS = 30 * 60 * 1_000;

const IMPORT_TARGET_PATHS: Record<TransferImportTarget, string> = {
    flows: 'graphs/',
    collections: 'source-collections/',
};

/** A job ended as failed; `message` is the reason the server gave. */
export class TransferJobFailedError extends Error {
    constructor(public readonly job: TransferJob) {
        super(job.error?.message || 'The job failed.');
        this.name = 'TransferJobFailedError';
    }
}

/** A job did not finish within TRANSFER_JOB_MAX_WAIT_MS; it may still finish on the server. */
export class TransferJobTimeoutError extends Error {
    constructor() {
        super('The job is taking too long. Try again later.');
        this.name = 'TransferJobTimeoutError';
    }
}

/** The message to show for a failed start, poll or download: the server's reason when it gave one. */
export function describeTransferError(error: unknown, fallback: string): string {
    if (error instanceof HttpErrorResponse) {
        return extractHttpErrorMessage(error, fallback);
    }
    return error instanceof Error && error.message ? error.message : fallback;
}

/**
 * Exports and imports that run as background jobs on the server: start one, wait for it to
 * finish, and download an export's archive.
 */
@Injectable({
    providedIn: 'root',
})
export class TransferJobsService {
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);

    startFlowExport(ids: number[], includeKnowledge: boolean): Observable<TransferJobCreated> {
        return this.http.post<TransferJobCreated>(`${this.apiUrl}graphs/export-jobs/`, {
            ids,
            include_knowledge: includeKnowledge,
        });
    }

    startCollectionExport(ids: number[]): Observable<TransferJobCreated> {
        return this.http.post<TransferJobCreated>(`${this.apiUrl}source-collections/export-jobs/`, { ids });
    }

    /** Uploads a `.zip` export as the raw request body; flow imports take the import settings. */
    startImport(
        target: TransferImportTarget,
        file: File,
        settings?: ImportFlowRequestOptions
    ): Observable<TransferJobCreated> {
        let params = new HttpParams();
        if (target === 'flows' && settings) {
            params = params
                .set('preserve_uuids', settings.preserveUuids)
                .set('replace_existing', settings.replaceExisting)
                .set('import_labels', settings.importLabels);
        }
        return this.http.post<TransferJobCreated>(`${this.apiUrl}${IMPORT_TARGET_PATHS[target]}import-jobs/`, file, {
            params,
            headers: { 'Content-Type': 'application/zip' },
        });
    }

    getJob(jobId: string): Observable<TransferJob> {
        return this.http.get<TransferJob>(`${this.apiUrl}transfer-jobs/${jobId}/`);
    }

    /**
     * Polls the job until it finishes and emits it once completed.
     * Errors with TransferJobFailedError when it failed, TransferJobTimeoutError when it ran too long.
     */
    waitForJob(jobId: string): Observable<TransferJob> {
        return timer(0, TRANSFER_JOB_POLL_INTERVAL_MS).pipe(
            exhaustMap(() => this.getJob(jobId)),
            first((job) => job.status === 'completed' || job.status === 'failed'),
            timeout({ first: TRANSFER_JOB_MAX_WAIT_MS, with: () => throwError(() => new TransferJobTimeoutError()) }),
            map((job) => {
                if (job.status === 'failed') {
                    throw new TransferJobFailedError(job);
                }
                return job;
            })
        );
    }

    /**
     * Asks for a single-use download link and navigates the browser to it, so the archive streams
     * to disk instead of into memory.
     */
    downloadExport(job: TransferJob): Observable<void> {
        return this.http
            .post<TransferJobDownloadTicket>(`${this.apiUrl}transfer-jobs/${job.id}/download-ticket/`, {})
            .pipe(map(({ download_url }) => this.navigateToDownload(download_url, job.file_name)));
    }

    private get apiUrl(): string {
        return this.configService.apiUrl;
    }

    private navigateToDownload(downloadUrl: string, fileName: string | null): void {
        // The link is relative to the API's origin, which is not always the page's.
        const apiBase = new URL(this.apiUrl, document.baseURI);
        const link = document.createElement('a');
        link.href = new URL(downloadUrl, apiBase).href;
        link.download = fileName ?? '';
        link.click();
    }
}
