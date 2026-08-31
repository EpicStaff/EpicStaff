import { computed, Injectable, signal } from '@angular/core';
import { deepEqual } from '@shared/utils';

import { UpdateNaiveRagDocumentDtoRequest } from '../models/naive-rag-document.model';

type PendingField = keyof UpdateNaiveRagDocumentDtoRequest;

/**
 * Owns the per-document "pending field edits" map — values the user has
 * changed in the UI but hasn't yet persisted to the backend.
 */
@Injectable({
    providedIn: 'root',
})
export class NaiveRagPendingEditsService {
    private pendingSignal = signal<Map<number, UpdateNaiveRagDocumentDtoRequest>>(new Map());
    public pending = this.pendingSignal.asReadonly();

    // Set of document IDs that currently have any pending fields — used by
    // the UI to show a rollback affordance next to changed rows.
    public pendingDocIds = computed<Set<number>>(() => new Set(this.pendingSignal().keys()));

    public setPendingField(
        documentId: number,
        field: PendingField,
        value: string | number | null,
        savedValue: unknown
    ): void {
        if (value === null) return;

        this.pendingSignal.update((prev) => {
            const next = new Map(prev);
            const current = { ...(next.get(documentId) ?? {}) };

            if (savedValue === value) {
                delete (current as Record<string, unknown>)[field];
            } else {
                (current as Record<string, unknown>)[field] = value;
            }

            if (Object.keys(current).length === 0) {
                next.delete(documentId);
            } else {
                next.set(documentId, current);
            }
            return next;
        });
    }

    /**
     * Sets multiple pending fields at once, comparing each against `baseline`.
     * Fields equal to baseline are stripped; empty resulting entries are
     * removed.
     */
    public setPendingFields(
        documentId: number,
        patch: UpdateNaiveRagDocumentDtoRequest,
        baseline?: Record<string, unknown>
    ): void {
        if (!baseline) return;

        this.pendingSignal.update((prev) => {
            const next = new Map(prev);
            const current: Record<string, unknown> = { ...(next.get(documentId) ?? {}) };

            for (const [key, value] of Object.entries(patch)) {
                if (value === undefined || value === null) continue;

                const baselineValue = baseline[key];
                if (deepEqual(baselineValue, value)) {
                    delete current[key];
                } else {
                    current[key] = value;
                }
            }

            if (Object.keys(current).length === 0) {
                next.delete(documentId);
            } else {
                next.set(documentId, current);
            }
            return next;
        });
    }

    /**
     * Drops pending entries for the given documents. Used by the row-level
     * "Revert" affordance and by save handlers to clear pending after the
     * server confirms the values.
     */
    public dropPending(documentIds: Iterable<number>): void {
        this.pendingSignal.update((prev) => {
            const next = new Map(prev);
            for (const id of documentIds) {
                next.delete(id);
            }
            return next;
        });
    }

    /**
     * Removes pending entries for docs that no longer exist on the server.
     * Called from the polling merge path.
     */
    public pruneOrphans(presentIds: Set<number>): void {
        this.pendingSignal.update((prev) => {
            let mutated = false;
            const next = new Map(prev);
            for (const id of prev.keys()) {
                if (!presentIds.has(id)) {
                    next.delete(id);
                    mutated = true;
                }
            }
            return mutated ? next : prev;
        });
    }

    public has(documentId: number): boolean {
        return this.pendingSignal().has(documentId);
    }

    public clear(): void {
        this.pendingSignal.set(new Map());
    }
}
