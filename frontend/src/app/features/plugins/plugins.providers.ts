import { Provider } from '@angular/core';
import { APP_STORAGE } from '@shared/services';

import { PluginsStoreService } from './services/plugins-store.service';

export function providePluginsStorages(): Provider[] {
    return [{ provide: APP_STORAGE, useExisting: PluginsStoreService, multi: true }];
}
