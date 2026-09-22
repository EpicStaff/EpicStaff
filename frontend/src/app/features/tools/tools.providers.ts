import { Provider } from '@angular/core';
import { APP_STORAGE } from '@shared/services';

import { ToolsLabelsStorageService } from './services/tools-labels-storage.service';
import { ToolsViewStorageService } from './services/tools-view-storage.service';

export function provideToolsStorages(): Provider[] {
    return [
        { provide: APP_STORAGE, useExisting: ToolsLabelsStorageService, multi: true },
        { provide: APP_STORAGE, useExisting: ToolsViewStorageService, multi: true },
    ];
}
