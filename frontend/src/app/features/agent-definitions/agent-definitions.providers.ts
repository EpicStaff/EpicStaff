import { Provider } from '@angular/core';
import { APP_STORAGE } from '@shared/services';

import { AgentGroupsStorageService } from './services/agent-groups-storage.service';

export function provideAgentDefinitionsStorages(): Provider[] {
    return [{ provide: APP_STORAGE, useExisting: AgentGroupsStorageService, multi: true }];
}
