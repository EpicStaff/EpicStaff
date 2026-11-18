import { Provider } from '@angular/core';
import { APP_STORAGE } from '@shared/services';

import { AuditFilterStorageService } from './services/audit-filter-storage.service';
import { AuditTokenService } from './services/audit-token.service';

export function provideAuditStorages(): Provider[] {
    return [
        { provide: APP_STORAGE, useExisting: AuditTokenService, multi: true },
        { provide: APP_STORAGE, useExisting: AuditFilterStorageService, multi: true },
    ];
}
