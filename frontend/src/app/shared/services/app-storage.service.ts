import { inject, Injectable } from '@angular/core';

import { APP_STORAGE } from './app-storage.token';
import { StorageService } from './storage-service.interface';

export type { StorageService } from './storage-service.interface';

@Injectable({ providedIn: 'root' })
export class AppStorageService {
    private readonly storages = inject(APP_STORAGE, { optional: true }) ?? [];

    clearAll(): void {
        this.storages.forEach((s) => s.clear());
    }

    /** Clears each given storage once (duplicates are ignored). */
    invalidate(storages: Iterable<StorageService>): void {
        new Set(storages).forEach((s) => s.clear());
    }
}
