import { Provider } from '@angular/core';
import { APP_STORAGE } from '@shared/services';

import { ChatDesksStorageService } from './services/chat-desks-storage.service';
import { ChatMyAliasesStorageService } from './services/chat-my-aliases-storage.service';

export function provideChatStorages(): Provider[] {
    return [
        { provide: APP_STORAGE, useExisting: ChatDesksStorageService, multi: true },
        { provide: APP_STORAGE, useExisting: ChatMyAliasesStorageService, multi: true },
    ];
}
