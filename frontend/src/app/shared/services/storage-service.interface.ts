/**
 * Minimal contract every "storage" service must implement so that
 * {@link AppStorageService} can reset all in-memory state on logout.
 *
 * Kept in its own leaf file (no feature imports) to avoid a circular
 * dependency between `app-storage.service.ts` and services that extend
 * or reference it (e.g. `base-labels-store.service.ts`).
 */
export interface StorageService {
    clear(): void;
}
