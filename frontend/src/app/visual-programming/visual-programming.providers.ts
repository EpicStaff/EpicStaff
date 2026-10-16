import { Provider } from '@angular/core';
import { APP_STORAGE } from '@shared/services';

import { CdtExplanationCacheService } from './services/cdt-explanation-cache.service';
import { ExecutionTimeoutLimitsStorageService } from './services/execution-timeout-limits-storage.service';

export function provideVisualProgrammingStorages(): Provider[] {
    return [
        { provide: APP_STORAGE, useExisting: CdtExplanationCacheService, multi: true },
        { provide: APP_STORAGE, useExisting: ExecutionTimeoutLimitsStorageService, multi: true },
    ];
}
