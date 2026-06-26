import { inject } from '@angular/core';
import { CanActivateFn } from '@angular/router';
import { forkJoin, map, of } from 'rxjs';

import { PermissionsService } from '../../services/auth/permissions.service';
import { ProfileService } from '../../services/auth/profile.service';

export const bootstrapGuard: CanActivateFn = () => {
    const profileService = inject(ProfileService);
    const permissionsService = inject(PermissionsService);

    const cached = profileService.currentUserSignal();
    if (cached && permissionsService.active() !== null) {
        permissionsService.loadCatalog().subscribe();
        return of(true);
    }

    return forkJoin([profileService.bootstrapUser(), permissionsService.loadCatalog()]).pipe(map(() => true));
};
