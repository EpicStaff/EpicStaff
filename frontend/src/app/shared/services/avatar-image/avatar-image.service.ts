import { effect, inject, Injectable, Signal, signal } from '@angular/core';
import { catchError, map, Observable, of, shareReplay } from 'rxjs';

import { AvatarImageApiService } from './avatar-image-api.service';

interface AvatarCacheEntry {
    objectUrl$: Observable<string | null>;
    objectUrl: string | null;
    refCount: number;
}

/** One holder's claim on a cached avatar. `release()` is idempotent. */
export interface AvatarImageLease {
    objectUrl$: Observable<string | null>;
    release(): void;
}

/**
 * Shares one object URL per avatar URL between every component showing it, and revokes it once the last one lets
 * go. Avatar URLs are versioned by the backend, so the URL itself is a safe cache key: a new upload is a new key.
 * Entries live only while a component holds them, so logout (which destroys the layout) empties the cache — that is
 * why this service is not registered with APP_STORAGE.
 *
 * A lease is bound to the entry it was taken from, not to the URL: a failed load drops its entry from the map so the
 * next acquire retries, and the holders of the failed entry must not then release the retry's entry.
 */
@Injectable({
    providedIn: 'root',
})
export class AvatarImageService {
    private readonly avatarImageApi = inject(AvatarImageApiService);
    private readonly entries = new Map<string, AvatarCacheEntry>();

    /** The lease emits the object URL, or null when there is no visible avatar (404) or loading failed. */
    acquire(avatarUrl: string): AvatarImageLease {
        let entry = this.entries.get(avatarUrl);
        if (!entry) {
            entry = this.createEntry(avatarUrl);
            this.entries.set(avatarUrl, entry);
        }
        entry.refCount++;

        const acquiredEntry = entry;
        let released = false;
        return {
            objectUrl$: acquiredEntry.objectUrl$,
            release: () => {
                if (released) return;
                released = true;
                this.releaseEntry(avatarUrl, acquiredEntry);
            },
        };
    }

    private releaseEntry(avatarUrl: string, entry: AvatarCacheEntry): void {
        entry.refCount--;
        if (entry.refCount > 0) return;

        if (this.entries.get(avatarUrl) === entry) {
            this.entries.delete(avatarUrl);
        }
        if (entry.objectUrl) {
            URL.revokeObjectURL(entry.objectUrl);
            entry.objectUrl = null;
        }
    }

    private createEntry(avatarUrl: string): AvatarCacheEntry {
        const entry: AvatarCacheEntry = { objectUrl$: of(null), objectUrl: null, refCount: 0 };
        entry.objectUrl$ = this.avatarImageApi.getAvatar(avatarUrl).pipe(
            map((blob) => this.storeObjectUrl(avatarUrl, entry, blob)),
            catchError(() => {
                // Current holders keep their fallback; dropping the entry lets the next acquire try again.
                if (this.entries.get(avatarUrl) === entry) {
                    this.entries.delete(avatarUrl);
                }
                return of(null);
            }),
            // refCount: the last holder unsubscribing cancels a request nobody is waiting for any more.
            shareReplay({ bufferSize: 1, refCount: true })
        );
        return entry;
    }

    private storeObjectUrl(avatarUrl: string, entry: AvatarCacheEntry, blob: Blob): string | null {
        const objectUrl = URL.createObjectURL(blob);
        // Released while the request was in flight: nobody will ever revoke it later, so do it now.
        if (this.entries.get(avatarUrl) !== entry) {
            URL.revokeObjectURL(objectUrl);
            return null;
        }
        entry.objectUrl = objectUrl;
        return objectUrl;
    }
}

/**
 * Turns an authenticated avatar URL into a displayable object URL for the calling component. Null while loading,
 * when there is no avatar, or when it cannot be loaded — callers show their fallback then. The image is released
 * when the source URL changes and when the component is destroyed. Must be called in an injection context.
 */
export function injectAvatarObjectUrl(source: Signal<string | null>): Signal<string | null> {
    const avatarImages = inject(AvatarImageService);
    const objectUrl = signal<string | null>(null);

    effect((onCleanup) => {
        const avatarUrl = source();
        objectUrl.set(null);
        if (!avatarUrl) return;

        const lease = avatarImages.acquire(avatarUrl);
        const subscription = lease.objectUrl$.subscribe((value) => objectUrl.set(value));
        onCleanup(() => {
            subscription.unsubscribe();
            lease.release();
        });
    });

    return objectUrl.asReadonly();
}
