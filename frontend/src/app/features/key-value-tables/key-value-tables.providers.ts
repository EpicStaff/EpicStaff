import { Provider } from '@angular/core';
import { APP_STORAGE } from '@shared/services';

import { KeyValueTablesStorageService } from './services/key-value-tables-storage.service';

export function provideKeyValueTablesStorages(): Provider[] {
    return [{ provide: APP_STORAGE, useExisting: KeyValueTablesStorageService, multi: true }];
}
