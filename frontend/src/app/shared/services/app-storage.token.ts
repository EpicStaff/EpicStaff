import { InjectionToken } from '@angular/core';

import { StorageService } from './storage-service.interface';

/**
 * Multi-provider collecting every storage that must be reset on logout.
 * Each feature registers its own storages through a provider function so
 * AppStorageService never has to name them, keeping shared independent of
 * features.
 */
export const APP_STORAGE = new InjectionToken<readonly StorageService[]>('APP_STORAGE');
