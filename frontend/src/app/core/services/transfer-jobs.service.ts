import { DOCUMENT } from '@angular/common';
import { HttpClient, HttpContext, HttpErrorResponse, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { extractHttpErrorMessage } from '@shared/utils';
import { defer, MonoTypeOperatorFunction, Observable, Subject, throwError, timer } from 'rxjs';
import { exhaustMap, finalize, first, map, retry, switchMap, takeUntil, tap, timeout } from 'rxjs/operators';

import { ActiveOrgService } from '../../services/auth/active-org.service';
import { SessionEndService } from '../../services/auth/session-end.service';
import { ConfigService } from '../../services/config';
import { ORG_ID_OVERRIDE } from '../interceptors/org-id-override.context';
import { ImportFlowRequestOptions, ImportResult } from '../models/import-result.model';
import {
    ExportFormat,
    TransferImportTarget,
    TransferJob,
    TransferJobCreated,
    TransferJobDownloadTicket,
    TransferJobKind,
    TransferJobListFilter,
    TransferJobPage,
    TransferJobPageRequest,
    TransferJobsCleared,
} from '../models/transfer-job.model';
import type { PartialExportRequest } from './import-export.service';

export const TRANSFER_JOB_POLL_INTERVAL_MS = 2_000;
export const TRANSFER_JOB_MAX_WAIT_MS = 30 * 60 * 1_000;
/** Polls that fail in a row on a network drop or a server error (5xx) before the wait gives up. */
export const TRANSFER_JOB_POLL_RETRIES = 5;
/** How long the hidden frame that downloads a cross-origin archive is kept, so the download can start. */
export const DOWNLOAD_FRAME_LIFETIME_MS = 60_000;

/** The longest uploaded file name the server keeps as an import job's name, in characters. */
const IMPORT_FILE_NAME_MAX_LENGTH = 255;

/** Shown when an import job completed without telling what it brought in. */
export const IMPORT_WITHOUT_SUMMARY_MESSAGE =
    'The import has finished, but the server did not report what it brought in. Check the list for the new items.';

const IMPORT_TARGET_PATHS: Record<TransferImportTarget, string> = {
    flows: 'graphs/',
    collections: 'source-collections/',
};

/** The filters an export of every session that matches them takes, in place of the sessions' ids. */
export interface SessionExportFilters {
    graph_id?: number;
    status?: string[];
    is_error_cause?: boolean;
    id_search?: string;
}

/** The body each export job takes, by what it exports. */
export interface ExportJobRequests {
    flows: { ids: number[]; include_knowledge: boolean };
    collections: { ids: number[] };
    pythonCodeTools: { ids: number[] };
    mcpTools: { ids: number[] };
    auditFilterPresets: { ids: number[] };
    sessions: ({ ids: number[] } | SessionExportFilters) & { export_format: ExportFormat };
    /** One node at a time. */
    classificationDecisionTables: { ids: [number]; export_format: ExportFormat };
}

export type ExportJobTarget = keyof ExportJobRequests;

const EXPORT_PATHS: Record<ExportJobTarget, string> = {
    flows: 'graphs/export-jobs/',
    collections: 'source-collections/export-jobs/',
    pythonCodeTools: 'python-code-tool/export-jobs/',
    mcpTools: 'mcp-tools/export-jobs/',
    auditFilterPresets: 'audit-filter-presets/export-jobs/',
    sessions: 'sessions/export-jobs/',
    classificationDecisionTables: 'classification-decision-table-node/export-jobs/',
};

const TIMEOUT_MESSAGES: Record<TransferJobKind, string> = {
    export:
        'The export is taking longer than usual and is still running on the server. Download it from Exports and ' +
        'imports once it is ready.',
    import:
        'The import is taking longer than usual and is still running on the server. Check the list again in a few ' +
        'minutes before you import the file again, so it is not imported twice.',
};

/**
 * A job the server accepted. `orgId` is the organization that was active when it started: every later request
 * about the job goes there, so switching organizations meanwhile does not lose it.
 */
export interface StartedTransferJob {
    id: string;
    kind: TransferJobKind;
    orgId: number | null;
}

/** A job ended as failed; `message` is the reason the server gave. */
export class TransferJobFailedError extends Error {
    constructor(public readonly job: TransferJob) {
        super(job.error?.message || 'The job failed.');
        this.name = 'TransferJobFailedError';
    }
}

/** A job did not finish within TRANSFER_JOB_MAX_WAIT_MS; it may still finish on the server. */
export class TransferJobTimeoutError extends Error {
    constructor(kind: TransferJobKind) {
        super(TIMEOUT_MESSAGES[kind]);
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
 * The name cut to what the server keeps. Cut by code point, as the server counts: a cut by UTF-16 unit could split
 * an emoji and leave a lone surrogate, which cannot be URL-encoded.
 */
function truncateFileName(name: string): string {
    return Array.from(name).slice(0, IMPORT_FILE_NAME_MAX_LENGTH).join('');
}

/** A network drop (0) or a server error (5xx) may pass; a 4xx, such as the job being gone, will not. */
function isTransientPollError(error: unknown): boolean {
    return error instanceof HttpErrorResponse && (error.status === 0 || error.status >= 500);
}

/**
 * Exports and imports that run as background jobs on the server: start one, wait for it to finish, and download
 * an export's archive. A sign-out ends every wait and download still running, without a value or an error.
 */
@Injectable({
    providedIn: 'root',
})
export class TransferJobsService {
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);
    private readonly activeOrg = inject(ActiveOrgService);
    private readonly sessionEnd = inject(SessionEndService);
    private readonly document = inject(DOCUMENT);

    private readonly startedSubject = new Subject<StartedTransferJob>();
    private readonly waitAbandonedSubject = new Subject<string>();
    /** How many waits in this tab follow each job right now. */
    private readonly waitCounts = new Map<string, number>();
    /** Jobs whose end a wait in this tab has passed on to its subscriber: completed, or failed. */
    private readonly endTold = new Set<string>();

    /** Emits every job this tab starts, once the server has accepted it. */
    readonly started$: Observable<StartedTransferJob> = this.startedSubject.asObservable();
    /**
     * Emits a job's id when the last wait for it stopped without passing on how the job ended: its subscriber
     * left (e.g. the page was closed), the wait gave up after TRANSFER_JOB_MAX_WAIT_MS, or a poll failed.
     */
    readonly waitAbandoned$: Observable<string> = this.waitAbandonedSubject.asObservable();

    constructor() {
        // Every wait ends on sign-out by itself (see untilSessionEnds).
        this.sessionEnd.ended$.pipe(takeUntilDestroyed()).subscribe(() => this.endTold.clear());
    }

    /** A wait in this tab follows the job right now, and will pass on how it ends. */
    isWaitedFor(jobId: string): boolean {
        return this.waitCounts.has(jobId);
    }

    /** A wait in this tab has already passed on how the job ended. */
    wasEndTold(jobId: string): boolean {
        return this.endTold.has(jobId);
    }

    startExport<Target extends ExportJobTarget>(
        target: Target,
        body: ExportJobRequests[Target]
    ): Observable<StartedTransferJob> {
        return this.startJob('export', (context) =>
            this.http.post<TransferJobCreated>(`${this.apiUrl}${EXPORT_PATHS[target]}`, body, { context })
        );
    }

    /** Exports nodes of a flow, picked in the flow editor. */
    startFlowNodesExport(graphId: number, body: PartialExportRequest): Observable<StartedTransferJob> {
        return this.startJob('export', (context) =>
            this.http.post<TransferJobCreated>(`${this.apiUrl}graphs/${graphId}/partial-export-jobs/`, body, {
                context,
            })
        );
    }

    /** The user's jobs in the active organization, newest first. */
    listJobs(filter: TransferJobListFilter = {}, page: TransferJobPageRequest = {}): Observable<TransferJobPage> {
        let params = new HttpParams();
        for (const status of filter.status ?? []) {
            params = params.append('status', status);
        }
        if (filter.kind) {
            params = params.set('kind', filter.kind);
        }
        if (page.limit !== undefined) {
            params = params.set('limit', page.limit);
        }
        if (page.offset !== undefined) {
            params = params.set('offset', page.offset);
        }
        return this.http.get<TransferJobPage>(`${this.apiUrl}transfer-jobs/`, { params });
    }

    /** Deletes a finished or queued job with its archive. A running job cannot be deleted: the server answers 409. */
    deleteJob(jobId: string): Observable<void> {
        return this.http.delete<void>(`${this.apiUrl}transfer-jobs/${jobId}/`);
    }

    /**
     * Deletes all the user's jobs in the active organization with their archives, except the running ones. Emits how
     * many were deleted.
     */
    clearJobs(): Observable<number> {
        return this.http
            .post<TransferJobsCleared>(`${this.apiUrl}transfer-jobs/clear/`, {})
            .pipe(map(({ deleted }) => deleted));
    }

    /**
     * Uploads a `.zip` export as the raw request body; flow imports take the import settings. The file's name goes
     * in the query, as the raw body carries none, and names the job in the list.
     */
    startImport(
        target: TransferImportTarget,
        file: File,
        settings?: ImportFlowRequestOptions
    ): Observable<StartedTransferJob> {
        let params = new HttpParams();
        const fileName = truncateFileName(file.name);
        if (fileName) {
            params = params.set('file_name', fileName);
        }
        if (target === 'flows' && settings) {
            params = params
                .set('preserve_uuids', settings.preserveUuids)
                .set('replace_existing', settings.replaceExisting)
                .set('import_labels', settings.importLabels);
        }
        return this.startJob('import', (context) =>
            this.http.post<TransferJobCreated>(`${this.apiUrl}${IMPORT_TARGET_PATHS[target]}import-jobs/`, file, {
                params,
                headers: { 'Content-Type': 'application/zip' },
                context,
            })
        );
    }

    /**
     * Imports a `.zip` export as a job and emits its summary once it has finished; `null` when the server gave
     * none. Errors as `waitForJob` does.
     */
    importAndWait(
        target: TransferImportTarget,
        file: File,
        settings?: ImportFlowRequestOptions
    ): Observable<ImportResult | null> {
        return this.startImport(target, file, settings).pipe(
            switchMap((started) => this.waitForJob(started)),
            map((job) => (job.kind === 'import' ? job.result : null))
        );
    }

    /**
     * Polls the job until it finishes and emits it once completed. A poll that fails on a network drop or a
     * server error is retried; any other failed poll ends the wait with its error.
     * Errors with TransferJobFailedError when the job failed, TransferJobTimeoutError when it ran too long.
     */
    waitForJob(started: StartedTransferJob): Observable<TransferJob> {
        return defer(() => {
            let endTold = false;
            this.addWait(started.id);
            return this.pollUntilEnded(started).pipe(
                tap({
                    next: () => (endTold = true),
                    error: (error: unknown) => (endTold = error instanceof TransferJobFailedError),
                }),
                finalize(() => this.removeWait(started.id, endTold))
            );
        });
    }

    /**
     * Asks for a single-use download link and has the browser download it, so the archive streams to disk instead
     * of into memory.
     */
    downloadExport(started: StartedTransferJob, fileName: string | null): Observable<void> {
        return this.http
            .post<TransferJobDownloadTicket>(
                `${this.apiUrl}transfer-jobs/${started.id}/download-ticket/`,
                {},
                { context: this.orgContext(started.orgId) }
            )
            .pipe(
                map(({ download_url }) => this.download(download_url, fileName)),
                this.untilSessionEnds()
            );
    }

    private get apiUrl(): string {
        return this.configService.apiUrl;
    }

    private pollUntilEnded(started: StartedTransferJob): Observable<TransferJob> {
        return timer(0, TRANSFER_JOB_POLL_INTERVAL_MS).pipe(
            exhaustMap(() =>
                this.http
                    .get<TransferJob>(`${this.apiUrl}transfer-jobs/${started.id}/`, {
                        context: this.orgContext(started.orgId),
                    })
                    .pipe(
                        retry({
                            count: TRANSFER_JOB_POLL_RETRIES,
                            delay: (error: unknown) =>
                                isTransientPollError(error)
                                    ? timer(TRANSFER_JOB_POLL_INTERVAL_MS)
                                    : throwError(() => error),
                        })
                    )
            ),
            first((job) => job.status === 'completed' || job.status === 'failed'),
            timeout({
                first: TRANSFER_JOB_MAX_WAIT_MS,
                with: () => throwError(() => new TransferJobTimeoutError(started.kind)),
            }),
            map((job) => {
                if (job.status === 'failed') {
                    throw new TransferJobFailedError(job);
                }
                return job;
            }),
            this.untilSessionEnds()
        );
    }

    private addWait(jobId: string): void {
        this.waitCounts.set(jobId, (this.waitCounts.get(jobId) ?? 0) + 1);
    }

    private removeWait(jobId: string, endTold: boolean): void {
        if (endTold) {
            this.endTold.add(jobId);
        }
        const remaining = (this.waitCounts.get(jobId) ?? 1) - 1;
        if (remaining > 0) {
            this.waitCounts.set(jobId, remaining);
            return;
        }
        this.waitCounts.delete(jobId);
        if (!this.endTold.has(jobId)) {
            this.waitAbandonedSubject.next(jobId);
        }
    }

    /** Starts a job in the organization active now and remembers it for the requests that follow. */
    private startJob(
        kind: TransferJobKind,
        post: (context: HttpContext) => Observable<TransferJobCreated>
    ): Observable<StartedTransferJob> {
        return defer(() => {
            const orgId = this.activeOrg.activeOrgId();
            return post(this.orgContext(orgId)).pipe(
                map(({ job_id }): StartedTransferJob => ({ id: job_id, kind, orgId })),
                tap((started) => this.startedSubject.next(started))
            );
        }).pipe(this.untilSessionEnds());
    }

    private orgContext(orgId: number | null): HttpContext {
        return new HttpContext().set(ORG_ID_OVERRIDE, orgId);
    }

    private untilSessionEnds<T>(): MonoTypeOperatorFunction<T> {
        return takeUntil(this.sessionEnd.ended$);
    }

    private download(downloadUrl: string, fileName: string | null): void {
        // The link is relative to the API's origin, which is not always the page's.
        const apiBase = new URL(this.apiUrl, this.document.baseURI);
        const url = new URL(downloadUrl, apiBase);
        if (url.origin === this.document.location.origin) {
            const link = this.document.createElement('a');
            link.href = url.href;
            link.download = fileName ?? '';
            link.click();
            return;
        }
        // A browser ignores `download` on a link to another origin and opens it in the tab instead, so an error
        // answer (an expired ticket) would replace the app. A hidden frame downloads the archive and keeps any
        // error out of sight.
        const frame = this.document.createElement('iframe');
        frame.hidden = true;
        frame.src = url.href;
        this.document.body.appendChild(frame);
        setTimeout(() => frame.remove(), DOWNLOAD_FRAME_LIFETIME_MS);
    }
}
