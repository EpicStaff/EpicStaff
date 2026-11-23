// Single source of truth for the `table-link-pairs/` matrix inside the knowledge-sources feature.
// Both `graph-rag-data-tables` (to decide which Linked-to tabs are allowed on the active subject)
// and `graph-rag-visualization` (to decide which tables are valid Open-in targets for a selected
// node/edge) read the same map through this store, and the backend request is issued at most once
// per browser session — the endpoint is per-service, not per-rag, and the backend caches it for an
// hour.
import { inject, Injectable, signal } from '@angular/core';
import { Observable, of, shareReplay } from 'rxjs';
import { catchError, finalize, tap } from 'rxjs/operators';

import { LINKED_TO_TARGET_TYPES, LinkedToTargetType } from '../components/graph-rag-linked-to-picker/linked-to-targets';
import { GraphRagService } from './graph-rag.service';

const KNOWN_TARGETS = new Set<string>(LINKED_TO_TARGET_TYPES);

@Injectable({ providedIn: 'root' })
export class GraphRagLinkPairsStore {
    private readonly graphRagService = inject(GraphRagService);

    private readonly pairs = signal<Record<string, string[]>>({});
    readonly allowedPairs = this.pairs.asReadonly();

    /** `true` while the first fetch is still in-flight; flips back to `false` on success OR failure. */
    private readonly loading = signal(false);
    readonly isLoading = this.loading.asReadonly();

    private request: Observable<Record<string, string[]>> | null = null;

    /**
     * Returns the cached matrix if loaded, otherwise issues the fetch and caches its response.
     * On failure the store exposes an empty map — the callers treat an empty matrix as "no allowed
     * pairs", which hides the picker entirely rather than blocking the view.
     */
    ensureLoaded(): Observable<Record<string, string[]>> {
        if (this.request) return this.request;
        this.loading.set(true);
        this.request = this.graphRagService.getTableLinkPairs().pipe(
            tap((pairs) => this.pairs.set(pairs)),
            catchError(() => {
                this.pairs.set({});
                return of<Record<string, string[]>>({});
            }),
            finalize(() => this.loading.set(false)),
            // Multiple callers subscribing before the first response resolves should share it.
            shareReplay({ bufferSize: 1, refCount: false })
        );
        return this.request;
    }

    /**
     * Narrows the backend response to the `LinkedToTargetType` union by dropping any unknown name.
     * A drift between frontend and backend table lists then only hides a tab instead of leaking an
     * untyped string into the pickers.
     */
    targetsForSubject(subject: string): readonly LinkedToTargetType[] {
        const raw = this.pairs()[subject] ?? [];
        return raw.filter((value): value is LinkedToTargetType => KNOWN_TARGETS.has(value));
    }

    /**
     * Inverse lookup used by "Open in": returns the subject tables that accept rows linked to
     * `type`. A relationship row's id, for instance, can be used to filter any subject `S` whose
     * `allowedPairs[S]` includes `'relationships'`.
     */
    subjectsAcceptingLinkedTo(type: LinkedToTargetType): readonly LinkedToTargetType[] {
        const result: LinkedToTargetType[] = [];
        const pairs = this.pairs();
        for (const [subject, targets] of Object.entries(pairs)) {
            if (!KNOWN_TARGETS.has(subject)) continue;
            if (targets.includes(type)) {
                result.push(subject as LinkedToTargetType);
            }
        }
        return result;
    }

    /** Test-only reset so beforeEach can bypass the per-session cache. */
    resetForTesting(): void {
        this.pairs.set({});
        this.request = null;
        this.loading.set(false);
    }
}
