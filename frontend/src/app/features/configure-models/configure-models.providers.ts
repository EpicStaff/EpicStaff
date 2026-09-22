import { Provider } from '@angular/core';
import { APP_STORAGE } from '@shared/services';

import { DefaultModelsStorageService } from './services/default-models-storage.service';

export function provideConfigureModelsStorages(): Provider[] {
    return [{ provide: APP_STORAGE, useExisting: DefaultModelsStorageService, multi: true }];
}
