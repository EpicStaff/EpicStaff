import { Provider } from '@angular/core';
import { APP_STORAGE } from '@shared/services';

import { AuditTokenService } from './services/audit-token.service';

export function provideAuditStorages(): Provider[] {
    return [{ provide: APP_STORAGE, useExisting: AuditTokenService, multi: true }];
}
