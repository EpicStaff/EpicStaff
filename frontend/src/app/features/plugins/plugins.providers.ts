import { Provider } from '@angular/core';
import { APP_STORAGE } from '@shared/services';

import { AvailablePluginsStorageService } from './services/available-plugins-storage.service';
import { PluginsAdminStorageService } from './services/plugins-admin-storage.service';

export function providePluginsStorages(): Provider[] {
    return [
        { provide: APP_STORAGE, useExisting: AvailablePluginsStorageService, multi: true },
        { provide: APP_STORAGE, useExisting: PluginsAdminStorageService, multi: true },
    ];
}
