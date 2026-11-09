import { HttpErrorResponse } from '@angular/common/http';
import { computed, inject, Injectable, signal } from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { pluralize } from '@shared/utils';
import { defer, EMPTY, forkJoin, Observable, of, Subject, timer } from 'rxjs';
import { catchError, exhaustMap, finalize, map, startWith, switchMap, takeUntil, takeWhile, tap } from 'rxjs/operators';

import { ActiveOrgService } from '../../services/auth/active-org.service';
import { ProfileService } from '../../services/auth/profile.service';
import { SessionEndService } from '../../services/auth/session-end.service';
import { ToastService } from '../../services/notifications';
import {
    ExportTransferJob,
    isDownloadableExport,
    isUnfinishedTransferJob,
    TransferJob,
    transferJobName,
    TransferJobPage,
    TransferJobStatus,
} from '../models/transfer-job.model';
import { describeTransferError, TransferJobsService } from './transfer-jobs.service';

/** How often the unfinished jobs are checked while there are any. */
export const TRANSFER_JOBS_LIST_POLL_INTERVAL_MS = 5_000;
/** A ready export's toast stays long enough to reach its Download button. */
export const EXPORT_READY_TOAST_DURATION_MS = 15_000;
/** How many jobs the list loads at first, and how many more each "show more" adds. */
export const TRANSFER_JOBS_PAGE_SIZE = 10;

const NOTHING_CLEARED_MESSAGE = 'Nothing to clear. Running jobs are kept.';

const UNFINISHED_STATUSES: TransferJobStatus[] = ['queued', 'running'];

type LoadState = 'idle' | 'loading' | 'loaded' | 'failed';
type LoadMoreState = 'idle' | 'loading' | 'failed';

/** The signed-in user in the active organization: the jobs listed belong to both. */
interface JobsOwner {
    userId: number;
    orgId: number;
}

function sameOwner(first: JobsOwner | null, second: JobsOwner | null): boolean {
    return first?.userId === second?.userId && first?.orgId === second?.orgId;
}

/**
 * The signed-in user's export and import jobs in the active organization, for the jobs panel and its badge.
 *
 * Loaded again when the user or the organization changes, and checked while any job is unfinished, so a job started
 * before a page refresh is followed to its end. The end of a job is announced with a toast when this tab saw the job
 * unfinished at its first load, or started it, and no wait in this tab told how it ended (the page that waited was
 * left, or the wait gave up); a ready export is offered for download, never downloaded on its own. A job another
 * open tab started is that tab's to announce. Stops on sign-out.
 *
 * Not registered with APP_STORAGE: the jobs follow the user and the organization signals, which a sign-out and an
 * organization switch both change.
 */
@Injectable({
    providedIn: 'root',
})
export class TransferJobsStoreService {
    private readonly transferJobs = inject(TransferJobsService);
    private readonly activeOrg = inject(ActiveOrgService);
    private readonly profile = inject(ProfileService);
    private readonly sessionEnd = inject(SessionEndService);
    private readonly toastService = inject(ToastService);

    private readonly jobsState = signal<readonly TransferJob[]>([]);
    private readonly totalCountState = signal(0);
    /** From their own query: the list holds only the newest jobs, so it may miss an older one still running. */
    private readonly unfinishedState = signal<readonly TransferJob[]>([]);
    private readonly loadState = signal<LoadState>('idle');
    private readonly clearingIdsState = signal<ReadonlySet<string>>(new Set());
    private readonly isClearingAllState = signal(false);
    private readonly loadMoreState = signal<LoadMoreState>('idle');

    /** Newest first: the first page, and every page `loadMore` added after it. */
    readonly jobs = this.jobsState.asReadonly();
    /** How many jobs the user has, listed or not. */
    readonly totalCount = this.totalCountState.asReadonly();
    /** How many of the user's jobs are not listed yet. */
    readonly remainingCount = computed(() => Math.max(this.totalCountState() - this.jobsState().length, 0));
    /** The next page is on its way. */
    readonly isLoadingMore = computed(() => this.loadMoreState() === 'loading');
    /** The last attempt to load the next page failed; `loadMore` tries again. */
    readonly loadMoreFailed = computed(() => this.loadMoreState() === 'failed');
    readonly unfinishedCount = computed(() => this.unfinishedState().length);
    /** The first load for this user and organization is running. */
    readonly isLoading = computed(() => this.loadState() === 'loading');
    /** Nothing could be loaded for this user and organization. */
    readonly loadFailed = computed(() => this.loadState() === 'failed');
    /** Jobs whose deletion is on its way to the server. */
    readonly clearingIds = this.clearingIdsState.asReadonly();
    /** Clearing all the jobs is on its way to the server. */
    readonly isClearingAll = this.isClearingAllState.asReadonly();
    /**
     * Something is left for `clearAll` to delete: a listed job that is not running, or jobs not listed yet, which may
     * be anything.
     */
    readonly hasClearableJobs = computed(
        () => this.remainingCount() > 0 || this.jobsState().some((job) => job.status !== 'running')
    );

    private readonly owner = computed<JobsOwner | null>(
        () => {
            const userId = this.profile.currentUserSignal()?.id;
            const orgId = this.activeOrg.activeOrgId();
            return userId != null && orgId != null ? { userId, orgId } : null;
        },
        { equal: sameOwner }
    );
    /** Jobs whose end this tab announces unless a wait here tells it: unfinished at the first load, or started here. */
    private readonly announceable = new Set<string>();
    private readonly reloads = new Subject<void>();
    /** Ends a page still loading when the jobs listed are forgotten. */
    private readonly resets = new Subject<void>();

    constructor() {
        this.transferJobs.started$.pipe(takeUntilDestroyed()).subscribe((started) => {
            this.announceable.add(started.id);
            this.reload();
        });
        this.transferJobs.waitAbandoned$.pipe(takeUntilDestroyed()).subscribe((jobId) => {
            const job = this.jobsState().find((listed) => listed.id === jobId);
            if (job) {
                this.announceIfEnded(job);
            }
        });
        this.sessionEnd.ended$.pipe(takeUntilDestroyed()).subscribe(() => this.reset());
        toObservable(this.owner)
            .pipe(
                switchMap((owner) => {
                    this.reset();
                    return owner === null ? EMPTY : this.followOwnerJobs();
                }),
                takeUntilDestroyed()
            )
            .subscribe();
    }

    /** Loads the list again, e.g. when the panel opens; a check of unfinished jobs restarts with it. */
    reload(): void {
        this.reloads.next();
    }

    /**
     * Adds the next page of older jobs after the ones listed. Jobs that arrived meanwhile push the older ones further
     * down the server's list, so the page may repeat some listed jobs: they are skipped, and the list is loaded again
     * to bring in the new ones.
     */
    loadMore(): void {
        if (this.loadState() !== 'loaded' || this.loadMoreState() === 'loading' || this.remainingCount() === 0) {
            return;
        }
        this.loadMoreState.set('loading');
        this.transferJobs
            .listJobs({}, { limit: TRANSFER_JOBS_PAGE_SIZE, offset: this.jobsState().length })
            .pipe(takeUntil(this.resets), takeUntil(this.sessionEnd.ended$))
            .subscribe({
                next: (page) => this.appendPage(page),
                error: () => this.loadMoreState.set('failed'),
            });
    }

    /** Downloads a completed export of the active organization. */
    download(job: ExportTransferJob): void {
        this.downloadFrom(job, this.activeOrg.activeOrgId());
    }

    /** Deletes a job and its archive. A running job stays: the server refuses to delete it. */
    clearJob(job: TransferJob): void {
        if (job.status === 'running' || this.clearingIdsState().has(job.id)) {
            return;
        }
        this.updateClearing(job.id, true);
        this.transferJobs
            .deleteJob(job.id)
            .pipe(finalize(() => this.updateClearing(job.id, false)))
            .subscribe({
                next: () => this.removeJob(job.id),
                error: (error: unknown) => {
                    if (error instanceof HttpErrorResponse && error.status === 404) {
                        this.removeJob(job.id);
                        return;
                    }
                    this.toastService.error(describeTransferError(error, 'Failed to clear the job.'));
                    // A 409: the job started running meanwhile.
                    this.reload();
                },
            });
    }

    /**
     * Deletes all the user's jobs and their archives, except the running ones, which the server keeps. The list and
     * the count of unfinished jobs are loaded again either way: a failed request may have deleted some of them.
     */
    clearAll(): void {
        if (this.isClearingAllState()) {
            return;
        }
        this.isClearingAllState.set(true);
        this.transferJobs
            .clearJobs()
            .pipe(finalize(() => this.isClearingAllState.set(false)))
            .subscribe({
                next: (deleted) => {
                    if (deleted === 0) {
                        // The list was out of date: the jobs left started running, or another tab cleared them.
                        this.toastService.info(NOTHING_CLEARED_MESSAGE);
                    } else {
                        this.toastService.success(`Cleared ${pluralize(deleted, 'job', 'jobs')}.`);
                    }
                    this.reload();
                },
                error: (error: unknown) => {
                    this.toastService.error(describeTransferError(error, 'Failed to clear the jobs.'));
                    this.reload();
                },
            });
    }

    private followOwnerJobs(): Observable<unknown> {
        return this.reloads.pipe(
            startWith(undefined),
            switchMap(() => this.loadThenPoll()),
            takeUntil(this.sessionEnd.ended$)
        );
    }

    private loadThenPoll(): Observable<unknown> {
        return defer(() => {
            if (this.loadState() !== 'loaded') {
                this.loadState.set('loading');
            }
            // As many jobs as are listed are loaded again, so a refresh keeps the pages the user has opened.
            const limit = Math.max(TRANSFER_JOBS_PAGE_SIZE, this.jobsState().length);
            return forkJoin([this.transferJobs.listJobs({}, { limit }), this.listUnfinished()]);
        }).pipe(
            tap(([page, unfinished]) => this.applyList(page, unfinished.results)),
            map(() => undefined),
            catchError(() => {
                if (this.loadState() !== 'loaded') {
                    this.loadState.set('failed');
                }
                return of(undefined);
            }),
            switchMap(() => this.pollUnfinished())
        );
    }

    /**
     * Asks for the unfinished jobs while there are any. When one of them has ended, or one started elsewhere, the
     * whole list is loaded again, which ends this check and starts the next one if anything is still unfinished.
     */
    private pollUnfinished(): Observable<unknown> {
        return timer(TRANSFER_JOBS_LIST_POLL_INTERVAL_MS, TRANSFER_JOBS_LIST_POLL_INTERVAL_MS).pipe(
            takeWhile(() => this.unfinishedCount() > 0),
            // A failed check is tried again at the next tick.
            exhaustMap(() => this.listUnfinished().pipe(catchError(() => EMPTY))),
            tap((page) => this.applyUnfinished(page.results))
        );
    }

    private listUnfinished(): Observable<TransferJobPage> {
        return this.transferJobs.listJobs({ status: UNFINISHED_STATUSES });
    }

    private applyList(page: TransferJobPage, unfinished: TransferJob[]): void {
        const isFirstLoad = this.loadState() !== 'loaded';
        this.jobsState.set([...page.results, ...this.olderThanPage(page)]);
        this.totalCountState.set(page.count);
        this.unfinishedState.set(unfinished);
        this.loadState.set('loaded');
        if (isFirstLoad) {
            // Unfinished when this tab loaded, e.g. before a refresh that ended their wait: this tab tells their end.
            unfinished.forEach((job) => this.announceable.add(job.id));
        }
        page.results.forEach((job) => this.announceIfEnded(job));
    }

    /**
     * The listed jobs older than the last one of a fresh first page, while the server has more than that page: new
     * jobs pushed them past its end, or a page was added while it loaded. Without more on the server, a listed job
     * missing from the page is gone.
     */
    private olderThanPage(page: TransferJobPage): TransferJob[] {
        if (page.count <= page.results.length) {
            return [];
        }
        const fresh = new Set(page.results.map((job) => job.id));
        const listed = this.jobsState();
        const lastFreshIndex = listed.reduce((last, job, index) => (fresh.has(job.id) ? index : last), -1);
        return listed.slice(lastFreshIndex + 1);
    }

    private appendPage(page: TransferJobPage): void {
        const listed = new Set(this.jobsState().map((job) => job.id));
        const older = page.results.filter((job) => !listed.has(job.id));
        this.jobsState.update((jobs) => [...jobs, ...older]);
        this.totalCountState.set(page.count);
        this.loadMoreState.set('idle');
        older.forEach((job) => this.announceIfEnded(job));
        if (older.length < page.results.length) {
            // Newer jobs shifted the page: load the list again so they show at its top.
            this.reload();
        }
    }

    private applyUnfinished(unfinished: TransferJob[]): void {
        const previous = new Set(this.unfinishedState().map((job) => job.id));
        const latest = new Set(unfinished.map((job) => job.id));
        const someEnded = [...previous].some((jobId) => !latest.has(jobId));
        const someNew = unfinished.some((job) => !previous.has(job.id));
        if (someEnded || someNew) {
            this.reload();
            return;
        }
        this.unfinishedState.set(unfinished);
        const byId = new Map(unfinished.map((job) => [job.id, job]));
        this.jobsState.update((jobs) => jobs.map((job) => byId.get(job.id) ?? job));
    }

    /** A wait still running here will tell how the job ended; if it is left, `waitAbandoned$` brings the job back. */
    private announceIfEnded(job: TransferJob): void {
        if (!this.announceable.has(job.id) || isUnfinishedTransferJob(job) || this.transferJobs.isWaitedFor(job.id)) {
            return;
        }
        this.announceable.delete(job.id);
        if (!this.transferJobs.wasEndTold(job.id)) {
            this.announceEnded(job);
        }
    }

    private announceEnded(job: TransferJob): void {
        const name = transferJobName(job);
        const action = job.kind === 'export' ? 'export' : 'import';
        if (job.status === 'failed') {
            this.toastService.error(`The ${action} of "${name}" failed. ${job.error?.message ?? ''}`.trim());
            return;
        }
        if (isDownloadableExport(job)) {
            const orgId = this.activeOrg.activeOrgId();
            this.toastService.success(
                `The export of "${name}" is ready. Its archive is also in Exports and imports.`,
                EXPORT_READY_TOAST_DURATION_MS,
                undefined,
                { action: { label: 'Download', run: () => this.downloadFrom(job, orgId) } }
            );
            return;
        }
        if (job.kind === 'import') {
            this.toastService.success(`The import of "${name}" has finished.`);
        }
    }

    private downloadFrom(job: ExportTransferJob, orgId: number | null): void {
        this.transferJobs.downloadExport({ id: job.id, kind: 'export', orgId }, job.file_name).subscribe({
            error: (error: unknown) => {
                this.toastService.error(describeTransferError(error, 'Failed to download the export.'));
                // A 410: the archive was removed to make room for newer exports; the list shows it.
                this.reload();
            },
        });
    }

    private removeJob(jobId: string): void {
        if (this.jobsState().some((job) => job.id === jobId)) {
            this.totalCountState.update((count) => Math.max(count - 1, 0));
        }
        this.jobsState.update((jobs) => jobs.filter((job) => job.id !== jobId));
        this.unfinishedState.update((jobs) => jobs.filter((job) => job.id !== jobId));
    }

    private updateClearing(jobId: string, clearing: boolean): void {
        this.clearingIdsState.update((ids) => {
            const next = new Set(ids);
            if (clearing) {
                next.add(jobId);
            } else {
                next.delete(jobId);
            }
            return next;
        });
    }

    private reset(): void {
        this.jobsState.set([]);
        this.totalCountState.set(0);
        this.unfinishedState.set([]);
        this.loadState.set('idle');
        this.clearingIdsState.set(new Set());
        this.loadMoreState.set('idle');
        this.resets.next();
        this.announceable.clear();
    }
}
