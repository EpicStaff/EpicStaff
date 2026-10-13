import { Provider } from '@angular/core';
import { APP_STORAGE } from '@shared/services';

import { SandboxLimitsStorageService } from './services/sandbox-limits-storage.service';

export function provideVisualProgrammingStorages(): Provider[] {
    return [{ provide: APP_STORAGE, useExisting: SandboxLimitsStorageService, multi: true }];
}
