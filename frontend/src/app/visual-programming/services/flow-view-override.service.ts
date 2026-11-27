import { HttpErrorResponse } from '@angular/common/http';
import { computed, DestroyRef, effect, inject, Injectable, signal, untracked } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { extractHttpErrorMessage, humanizeErrorMessage } from '@shared/utils';
import {
    BehaviorSubject,
    catchError,
    concatMap,
    EMPTY,
    finalize,
    first,
    map,
    Observable,
    Subject,
    Subscription,
    switchMap,
    tap,
} from 'rxjs';

import { ProfileService } from '../../services/auth/profile.service';
import { ToastService } from '../../services/notifications';
import { FlowViewOverride, FlowViewSettingsApiService } from './flow-view-settings-api.service';

interface FlowOverride {
    readonly graphId: number;
    readonly settings: FlowViewOverride;
}

/** Changes made before the stored override is known, to be put on top of it once it arrives. */
interface PendingEdits {
    /** The user who made them; they are saved only while that user is signed in. */
    readonly userId: number;
    /** The keys the user changed, with their new values; `undefined` drops the key. */
    readonly changes: Readonly<Record<string, unknown>>;
    /** "Reset to my defaults" was used, so the stored keys go too. */
    readonly dropsStored: boolean;
}

type LoadState = 'loading' | 'loaded' | 'failed';

/** One opening of a flow in the editor: what this tab knows of the stored override, and the changes made to it. */
interface FlowVisit {
    /** Orders the visits, so the load of one waits only for the changes of the visits before it. */
    readonly order: number;
    readonly graphId: number;
    loadState: LoadState;
    /** What the server holds, as far as this tab knows; `null` until it is loaded. */
    confirmed: FlowViewOverride | null;
    pending: PendingEdits | null;
    loading: Subscription | null;
    /** Numbers the writes, so a failed one rolls back only when no newer write is queued behind it. */
    writeSequence: number;
}

interface OverrideWrite {
    readonly visit: FlowVisit;
    /** The user who made the change; the write is dropped once another user, or nobody, is signed in. */
    readonly userId: number;
    readonly settings: FlowViewOverride;
    readonly sequence: number;
}

/**
 * The signed-in user's own view settings for the open flow. Loaded when a flow opens and cleared when it is left,
 * so the next flow, or a page outside the editor, never shows this flow's override. A change shows at once and is
 * saved in the background; saves go out one at a time, in order, each carrying the whole override. A failed save
 * brings back what the server holds and says why in a toast. A change is saved only for the user who made it: a
 * save still waiting when that user signs out, or another user signs in, is dropped. With nobody signed in, a
 * change is ignored.
 *
 * Every save replaces the whole stored override, so none is sent before the stored one is known: a change made
 * while it loads waits, and is put on top of it once it arrives, even when the flow has been left by then. The
 * stored override is loaded only once the saves and waiting changes of the flow's earlier openings have settled,
 * so reopening a flow never shows a value older than what this tab saved. When it can't be loaded, the next change
 * loads it again; if that fails too, or the flow has been left, the change is taken back and a toast says it was
 * not saved. So a change never replaces stored keys this tab has not seen.
 */
@Injectable({ providedIn: 'root' })
export class FlowViewOverrideService {
    private readonly api = inject(FlowViewSettingsApiService);
    private readonly profileService = inject(ProfileService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    private readonly current = signal<FlowOverride | null>(null);
    readonly override = computed<FlowViewOverride>(() => this.current()?.settings ?? {});

    private visit: FlowVisit | null = null;
    private visitCount = 0;
    /** Visits left while a change made during their load still waited for the stored override. */
    private readonly leftWithEdits = new Set<FlowVisit>();
    /** The flow of each write queued or on its way, one entry per write. */
    private readonly unsettledWrites: number[] = [];
    /** Emits whenever a write or a left visit's changes settle, so a load waiting for them checks again. */
    private readonly settled = new BehaviorSubject<void>(undefined);
    private readonly writes = new Subject<OverrideWrite>();

    constructor() {
        // The waiting changes of a user who signed out stop at once; a queued write is checked again when it is sent.
        effect(() => {
            const userId = this.profileService.currentUserSignal()?.id;
            untracked(() => this.dropEditsOfOtherUsers(userId));
        });
        this.writes
            .pipe(
                concatMap((write) => this.send(write).pipe(finalize(() => this.writeSettled(write)))),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe();
    }

    /** Starts showing the override of flow `graphId`; until it arrives, and if it can't be loaded, there is none. */
    load(graphId: number): void {
        this.leave();
        this.visitCount += 1;
        const visit: FlowVisit = {
            order: this.visitCount,
            graphId,
            loadState: 'loading',
            confirmed: null,
            pending: null,
            loading: null,
            writeSequence: 0,
        };
        this.visit = visit;
        this.current.set({ graphId, settings: {} });
        this.fetch(visit);
    }

    /**
     * Leaves the flow: no override shows any more. Saves already started still reach the server, and a change made
     * while the override loaded is still put on top of it and saved, or reported in a toast when it can't be.
     */
    clear(): void {
        this.leave();
    }

    /** Replaces the open flow's override with `settings`; an empty one removes it. Ignored with no flow open. */
    save(settings: FlowViewOverride): void {
        this.change(settings, false);
    }

    /** Drops the open flow's override, so the flow follows the account's settings again. */
    reset(): void {
        this.change({}, true);
    }

    private leave(): void {
        const visit = this.visit;
        this.visit = null;
        this.current.set(null);
        if (visit === null) return;
        if (visit.pending === null) {
            visit.loading?.unsubscribe();
            visit.loading = null;
            return;
        }
        // Its load goes on, so the change is put on top of the stored override and saved once it arrives.
        this.leftWithEdits.add(visit);
    }

    private change(settings: FlowViewOverride, dropsStored: boolean): void {
        const visit = this.visit;
        const userId = this.profileService.currentUserSignal()?.id;
        if (visit === null || userId === undefined) return;
        const shown = this.override();
        this.current.set({ graphId: visit.graphId, settings });
        if (visit.loadState === 'loaded') {
            this.enqueue(visit, userId, settings);
            return;
        }
        visit.pending = dropsStored
            ? { userId, changes: {}, dropsStored: true }
            : {
                  userId,
                  changes: { ...visit.pending?.changes, ...changedKeys(shown, settings) },
                  dropsStored: visit.pending?.dropsStored ?? false,
              };
        if (visit.loadState === 'failed') this.fetch(visit);
    }

    /** Loads the stored override once the saves and waiting changes of the flow's earlier visits have settled. */
    private fetch(visit: FlowVisit): void {
        visit.loading?.unsubscribe();
        visit.loadState = 'loading';
        visit.loading = this.settled
            .pipe(
                first(() => !this.hasUnsettledChangesBefore(visit)),
                switchMap(() => this.api.get(visit.graphId))
            )
            .subscribe({
                next: (stored) => this.loaded(visit, stored),
                error: (error: HttpErrorResponse) => this.loadFailed(visit, error),
            });
    }

    private hasUnsettledChangesBefore(visit: FlowVisit): boolean {
        if (this.unsettledWrites.includes(visit.graphId)) return true;
        return [...this.leftWithEdits].some((other) => other.graphId === visit.graphId && other.order < visit.order);
    }

    private loaded(visit: FlowVisit, stored: FlowViewOverride): void {
        visit.loading = null;
        visit.loadState = 'loaded';
        visit.confirmed = stored;
        const pending = visit.pending;
        visit.pending = null;
        const settings = pending === null ? stored : withChanges(pending.dropsStored ? {} : stored, pending.changes);
        if (this.visit === visit) this.current.set({ graphId: visit.graphId, settings });
        // Queued before the visit's changes count as settled, so a load waiting for them waits for the write too.
        if (pending !== null && !sameSettings(settings, stored)) this.enqueue(visit, pending.userId, settings);
        this.editsSettled(visit);
    }

    /** With no change waiting the flow opens with the account's settings; a waiting change is taken back. */
    private loadFailed(visit: FlowVisit, error: HttpErrorResponse): void {
        visit.loading = null;
        visit.loadState = 'failed';
        const pending = visit.pending;
        visit.pending = null;
        this.editsSettled(visit);
        if (pending === null) return;
        if (this.visit === visit) this.current.set({ graphId: visit.graphId, settings: {} });
        this.toastSaveError(error);
    }

    private editsSettled(visit: FlowVisit): void {
        if (this.leftWithEdits.delete(visit)) this.settled.next();
    }

    /** Drops the changes still waiting for a stored override that `userId`, the signed-in user, did not make. */
    private dropEditsOfOtherUsers(userId: number | undefined): void {
        for (const visit of [...this.leftWithEdits]) {
            if (visit.pending?.userId === userId) continue;
            visit.loading?.unsubscribe();
            visit.loading = null;
            visit.pending = null;
            this.editsSettled(visit);
        }
        const open = this.visit;
        if (open?.pending && open.pending.userId !== userId) {
            open.pending = null;
            this.current.set({ graphId: open.graphId, settings: open.confirmed ?? {} });
        }
    }

    private enqueue(visit: FlowVisit, userId: number, settings: FlowViewOverride): void {
        visit.writeSequence += 1;
        this.unsettledWrites.push(visit.graphId);
        this.writes.next({ visit, userId, settings, sequence: visit.writeSequence });
    }

    private writeSettled(write: OverrideWrite): void {
        const index = this.unsettledWrites.indexOf(write.visit.graphId);
        if (index !== -1) this.unsettledWrites.splice(index, 1);
        this.settled.next();
    }

    private send(write: OverrideWrite): Observable<unknown> {
        if (write.userId !== this.profileService.currentUserSignal()?.id) return EMPTY;
        const { visit } = write;
        const request: Observable<FlowViewOverride> =
            Object.keys(write.settings).length === 0
                ? this.api.delete(visit.graphId).pipe(map((): FlowViewOverride => ({})))
                : this.api.put(visit.graphId, write.settings);
        return request.pipe(
            tap((saved) => {
                visit.confirmed = saved;
            }),
            catchError((error: HttpErrorResponse) => {
                const isLatest = write.sequence === visit.writeSequence;
                if (isLatest && this.visit === visit && visit.confirmed !== null) {
                    this.current.set({ graphId: visit.graphId, settings: visit.confirmed });
                }
                this.toastSaveError(error);
                return EMPTY;
            })
        );
    }

    private toastSaveError(error: HttpErrorResponse): void {
        const reason = humanizeErrorMessage(extractHttpErrorMessage(error, ''));
        this.toastService.error(
            reason ? `Could not save the flow setting: ${reason}` : 'Could not save the flow setting'
        );
    }
}

/** The keys whose value differs between `before` and `after`, with the value in `after`. */
function changedKeys(before: FlowViewOverride, after: FlowViewOverride): Record<string, unknown> {
    const beforeValues = before as Readonly<Record<string, unknown>>;
    const afterValues = after as Readonly<Record<string, unknown>>;
    const keys = new Set([...Object.keys(beforeValues), ...Object.keys(afterValues)]);
    const changes: Record<string, unknown> = {};
    for (const key of keys) {
        if (beforeValues[key] !== afterValues[key]) changes[key] = afterValues[key];
    }
    return changes;
}

/** `base` with `changes` put on top; a change to `undefined` drops the key. */
function withChanges(base: FlowViewOverride, changes: Readonly<Record<string, unknown>>): FlowViewOverride {
    const result: Record<string, unknown> = { ...base };
    for (const [key, value] of Object.entries(changes)) {
        if (value === undefined) delete result[key];
        else result[key] = value;
    }
    return result as FlowViewOverride;
}

function sameSettings(left: FlowViewOverride, right: FlowViewOverride): boolean {
    const leftValues = left as Readonly<Record<string, unknown>>;
    const rightValues = right as Readonly<Record<string, unknown>>;
    const leftKeys = Object.keys(leftValues);
    return (
        leftKeys.length === Object.keys(rightValues).length &&
        leftKeys.every((key) => leftValues[key] === rightValues[key])
    );
}
