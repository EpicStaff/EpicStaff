import { Provider } from '@angular/core';
import { APP_STORAGE } from '@shared/services';

import { FlowsStorageService } from './services/flows-storage.service';
import { LabelsStorageService } from './services/labels-storage.service';

export function provideFlowsStorages(): Provider[] {
    return [
        { provide: APP_STORAGE, useExisting: LabelsStorageService, multi: true },
        { provide: APP_STORAGE, useExisting: FlowsStorageService, multi: true },
    ];
}
