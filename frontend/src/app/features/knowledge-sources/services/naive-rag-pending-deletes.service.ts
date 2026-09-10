import { inject, Injectable, signal } from '@angular/core';
import { EMPTY, Observable, throwError } from 'rxjs';
import { catchError, tap } from 'rxjs/operators';

import { BulkDeleteNaiveRagDocumentDtoResponse } from '../models/naive-rag-document.model';
import { NaiveRagService } from './naive-rag.service';

/**
 * Owns the "soft delete" set — IDs of docs the user has marked for deletion
 * in the UI but hasn't yet flushed to the backend. Also owns the hard bulk
 * delete HTTP call. State cleanup (removing deleted docs from other domains
 * like the docs catalog, pending edits, chunk states) is coordinated by
 * `NaiveRagDocumentsStorageService` via the returned response.
 */
@Injectable({
    providedIn: 'root',
})
export class NaiveRagPendingDeletesService {
    private readonly naiveRagService = inject(NaiveRagService);

    private pendingDeleteIdsSignal = signal<Set<number>>(new Set());
    public pendingDeleteIds = this.pendingDeleteIdsSignal.asReadonly();

    /**
     * Adds `id` to the pending-delete set. No effect if it was already there.
     * Returns true if the set actually mutated. The caller is responsible for
     * unchecking / removing the doc from other views.
     */
    public markPendingDelete(id: number): boolean {
        let mutated = false;
        this.pendingDeleteIdsSignal.update((prev) => {
            if (prev.has(id)) return prev;
            const next = new Set(prev);
            next.add(id);
            mutated = true;
            return next;
        });
        return mutated;
    }

    public clearPendingDeletes(): void {
        if (this.pendingDeleteIdsSignal().size === 0) return;
        this.pendingDeleteIdsSignal.set(new Set());
    }

    /**
     * Runs the actual bulk-delete HTTP call for the IDs currently marked for
     * deletion. Returns EMPTY when nothing is pending. On success, the
     * pending-delete set is cleaned of IDs the server confirms deleted via
     * `applyDeleted`.
     */
    public bulkDeletePending(ragId: number): Observable<BulkDeleteNaiveRagDocumentDtoResponse> {
        const ids = Array.from(this.pendingDeleteIdsSignal());
        if (!ids.length) return EMPTY;
        return this.bulkDelete(ragId, ids);
    }

    /**
     * Direct hard-delete of the given IDs, bypassing the soft-delete set.
     * On success `applyDeleted` prunes any that were also in the pending set.
     */
    public bulkDelete(ragId: number, ids: number[]): Observable<BulkDeleteNaiveRagDocumentDtoResponse> {
        if (!ids.length) return EMPTY;

        return this.naiveRagService.bulkDeleteDocumentConfigs(ragId, { config_ids: ids }).pipe(
            tap((response) => this.applyDeleted(response.deleted_config_ids)),
            catchError((err) => throwError(() => err))
        );
    }

    /**
     * Removes the given IDs from the pending-delete set. Called internally
     * after a successful bulk delete, and from the coordinator during the
     * polling merge (defensive prune for docs that vanished elsewhere).
     */
    public applyDeleted(ids: Iterable<number>): void {
        this.pendingDeleteIdsSignal.update((prev) => {
            if (prev.size === 0) return prev;
            let mutated = false;
            const next = new Set(prev);
            for (const id of ids) {
                if (next.delete(id)) mutated = true;
            }
            return mutated ? next : prev;
        });
    }

    /**
     * Removes pending-delete IDs whose docs no longer exist on the server.
     * Called from the polling merge path.
     */
    public pruneOrphans(presentIds: Set<number>): void {
        this.pendingDeleteIdsSignal.update((prev) => {
            if (prev.size === 0) return prev;
            let mutated = false;
            const next = new Set(prev);
            for (const id of prev) {
                if (!presentIds.has(id)) {
                    next.delete(id);
                    mutated = true;
                }
            }
            return mutated ? next : prev;
        });
    }

    public has(id: number): boolean {
        return this.pendingDeleteIdsSignal().has(id);
    }

    public clear(): void {
        this.pendingDeleteIdsSignal.set(new Set());
    }
}
