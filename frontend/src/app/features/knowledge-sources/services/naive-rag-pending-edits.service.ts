import { computed, Injectable, signal } from '@angular/core';
import { deepEqual } from '@shared/utils';

import { UpdateNaiveRagDocumentDtoRequest } from '../models/naive-rag-document.model';

type PendingField = keyof UpdateNaiveRagDocumentDtoRequest;
type PendingPatch = UpdateNaiveRagDocumentDtoRequest;

interface HistoryEntry {
    documentId: number;
    before: PendingPatch | undefined;
}

/**
 * Owns the per-document "pending field edits" map — values the user has
 * changed in the UI but hasn't yet persisted to the backend.
 */
@Injectable({
    providedIn: 'root',
})
export class NaiveRagPendingEditsService {
    private pendingSignal = signal<Map<number, PendingPatch>>(new Map());
    public pending = this.pendingSignal.asReadonly();

    // Set of document IDs that currently have any pending fields — used by
    // the UI to show a rollback affordance next to changed rows.
    public pendingDocIds = computed<Set<number>>(() => new Set(this.pendingSignal().keys()));

    private historySignal = signal<HistoryEntry[]>([]);

    public setPendingField(
        documentId: number,
        field: PendingField,
        value: string | number | null,
        savedValue: unknown
    ): void {
        // No early-return on null: a cleared nullable numeric field (e.g.
        // chunk_overlap) legitimately stages as null — it's diffed against
        // savedValue exactly like any other value below.
        this.pendingSignal.update((prev) => {
            const before = prev.get(documentId);
            const current = { ...(before ?? {}) };

            if (savedValue === value) {
                delete (current as Record<string, unknown>)[field];
            } else {
                (current as Record<string, unknown>)[field] = value;
            }

            const after = Object.keys(current).length === 0 ? undefined : current;
            if (deepEqual(before, after)) return prev;

            this.pushHistory(documentId, before);
            const next = new Map(prev);
            if (after === undefined) next.delete(documentId);
            else next.set(documentId, after);
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
            const before = prev.get(documentId);
            const current: Record<string, unknown> = { ...(before ?? {}) };

            for (const [key, value] of Object.entries(patch)) {
                if (value === undefined || value === null) continue;

                const baselineValue = baseline[key];
                if (deepEqual(baselineValue, value)) {
                    delete current[key];
                } else {
                    current[key] = value;
                }
            }

            const after = Object.keys(current).length === 0 ? undefined : (current as PendingPatch);
            if (deepEqual(before, after)) return prev;

            this.pushHistory(documentId, before);
            const next = new Map(prev);
            if (after === undefined) next.delete(documentId);
            else next.set(documentId, after);
            return next;
        });
    }

    private pushHistory(documentId: number, before: PendingPatch | undefined): void {
        this.historySignal.update((prev) => [...prev, { documentId, before }]);
    }

    public undoLast(): number | null {
        const stack = this.historySignal();
        if (stack.length === 0) return null;

        const entry = stack[stack.length - 1];
        this.historySignal.set(stack.slice(0, -1));
        this.pendingSignal.update((prev) => {
            const next = new Map(prev);
            if (entry.before === undefined) next.delete(entry.documentId);
            else next.set(entry.documentId, entry.before);
            return next;
        });
        return entry.documentId;
    }

    public dropPending(documentIds: Iterable<number>): void {
        const idSet = new Set(documentIds);
        if (idSet.size === 0) return;

        this.pendingSignal.update((prev) => {
            const next = new Map(prev);
            for (const id of idSet) {
                next.delete(id);
            }
            return next;
        });
        this.historySignal.update((prev) => {
            const filtered = prev.filter((entry) => !idSet.has(entry.documentId));
            return filtered.length === prev.length ? prev : filtered;
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
        this.historySignal.update((prev) => {
            const filtered = prev.filter((entry) => presentIds.has(entry.documentId));
            return filtered.length === prev.length ? prev : filtered;
        });
    }

    public has(documentId: number): boolean {
        return this.pendingSignal().has(documentId);
    }

    public clear(): void {
        this.pendingSignal.set(new Map());
        this.historySignal.set([]);
    }
}
