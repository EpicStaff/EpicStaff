import { Injectable } from '@angular/core';
import { StorageService } from '@shared/services';

import { clearStoredAuditFilters } from '../utils/audit-filter-storage.util';

// Cleared on sign-out and org switch (APP_STORAGE): a saved filter belongs to the person who set it, and the
// next person signing in to the same browser must not get it pre-applied.
@Injectable({ providedIn: 'root' })
export class AuditFilterStorageService implements StorageService {
    clear(): void {
        clearStoredAuditFilters();
    }
}
