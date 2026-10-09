import { inject, Injectable } from '@angular/core';
import { catchError, concatMap, defer, EMPTY, Observable, Subject, tap } from 'rxjs';

import { ToastService } from '../../../services/notifications';
import { CreateCollectionDtoResponse } from '../models/collection.model';
import { CollectionsStorageService } from './collections-storage.service';

/** Delay after the last keystroke before an autosaved field is saved. */
export const COLLECTION_AUTOSAVE_DEBOUNCE_MS = 600;

export type SavedCollectionField = 'collection_name' | 'description';

/** One value of one field, bound to the collection it was typed for. */
export interface CollectionFieldSave {
    collectionId: number;
    field: SavedCollectionField;
    value: string;
}

interface PendingSave {
    save: CollectionFieldSave;
    timer: ReturnType<typeof setTimeout>;
}

/**
 * Saves single collection fields, either as the user types (`schedule`, debounced) or on request (`save`).
 * Lives at the root, not in the editing component, so an edit always reaches the collection it was made for:
 * a save waiting out its debounce, or already sent, survives the editor being destroyed (a spinner while
 * another collection loads, leaving the page) — the same reason file downloads are not tied to the page
 * either. Saves go out one at a time, in order, with the "Collection Updated" / "Collection Update failed"
 * toasts.
 */
@Injectable({
    providedIn: 'root',
})
export class CollectionFieldSaveService {
    private readonly collectionsStorageService = inject(CollectionsStorageService);
    private readonly toastService = inject(ToastService);

    private readonly savedSubject = new Subject<CollectionFieldSave>();
    private readonly failedSubject = new Subject<CollectionFieldSave>();
    /** Saves that settled without an error, including those skipped because the value was already stored. */
    readonly saved$ = this.savedSubject.asObservable();
    /** Saves the backend rejected; the value is not stored. */
    readonly failed$ = this.failedSubject.asObservable();

    private readonly pending = new Map<string, PendingSave>();
    private readonly queue = new Subject<CollectionFieldSave>();

    constructor() {
        // Never unsubscribed on purpose: see the class comment. One queue serves every collection, so a hung
        // PATCH delays all later saves — accepted for now.
        this.queue.pipe(concatMap((save) => this.send(save))).subscribe();
    }

    /** Saves `save` once no newer value for the same collection and field arrives within the debounce. */
    schedule(save: CollectionFieldSave): void {
        const key = this.keyOf(save.collectionId, save.field);
        this.cancel(save.collectionId, save.field);
        const timer = setTimeout(() => this.flushKey(key), COLLECTION_AUTOSAVE_DEBOUNCE_MS);
        this.pending.set(key, { save, timer });
    }

    /** Saves `save` now, replacing a value of the same field still waiting out its debounce. */
    save(save: CollectionFieldSave): void {
        this.cancel(save.collectionId, save.field);
        this.queue.next(save);
    }

    /** Drops a value still waiting out its debounce, e.g. because the field became invalid since. */
    cancel(collectionId: number, field: SavedCollectionField): void {
        const key = this.keyOf(collectionId, field);
        const entry = this.pending.get(key);
        if (!entry) return;
        clearTimeout(entry.timer);
        this.pending.delete(key);
    }

    /** Sends the collection's waiting values now, without waiting out the debounce. */
    flush(collectionId: number): void {
        for (const [key, entry] of this.pending) {
            if (entry.save.collectionId === collectionId) this.flushKey(key);
        }
    }

    private flushKey(key: string): void {
        const entry = this.pending.get(key);
        if (!entry) return;
        clearTimeout(entry.timer);
        this.pending.delete(key);
        this.queue.next(entry.save);
    }

    private send(save: CollectionFieldSave): Observable<unknown> {
        return defer(() => {
            // Checked when sending, after every earlier save has updated the cache — not when queued, which
            // would drop "A" after "A" → "AB" (in flight) → "A".
            if (this.storedValue(save) === save.value) {
                this.savedSubject.next(save);
                return EMPTY;
            }
            return this.collectionsStorageService.updateCollectionById(save.collectionId, this.patchOf(save)).pipe(
                tap(() => {
                    this.toastService.success('Collection Updated');
                    this.savedSubject.next(save);
                }),
                catchError(() => {
                    this.toastService.error('Collection Update failed');
                    this.failedSubject.next(save);
                    return EMPTY;
                })
            );
        });
    }

    private storedValue({ collectionId, field }: CollectionFieldSave): string | undefined {
        const collection = this.collectionsStorageService
            .fullCollections()
            .find((candidate) => candidate.collection_id === collectionId);
        return collection ? (collection[field] ?? '') : undefined;
    }

    private patchOf({ field, value }: CollectionFieldSave): Partial<CreateCollectionDtoResponse> {
        return field === 'collection_name' ? { collection_name: value } : { description: value };
    }

    private keyOf(collectionId: number, field: SavedCollectionField): string {
        return `${collectionId}:${field}`;
    }
}
