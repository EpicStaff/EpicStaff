import { Provider } from '@angular/core';
import { APP_STORAGE } from '@shared/services';

import { OrganizationsStorageService } from './services/admin/organizations-storage.service';
import { RolesService } from './services/admin/roles.service';

export function provideRoleBaseAccessStorages(): Provider[] {
    return [
        { provide: APP_STORAGE, useExisting: RolesService, multi: true },
        { provide: APP_STORAGE, useExisting: OrganizationsStorageService, multi: true },
    ];
}
