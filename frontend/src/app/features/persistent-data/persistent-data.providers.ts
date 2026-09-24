import { Provider } from '@angular/core';
import { APP_STORAGE } from '@shared/services';

import { PersistenceTablesStorageService } from './services/persistence-tables-storage.service';

export function providePersistentDataStorages(): Provider[] {
    return [{ provide: APP_STORAGE, useExisting: PersistenceTablesStorageService, multi: true }];
}
