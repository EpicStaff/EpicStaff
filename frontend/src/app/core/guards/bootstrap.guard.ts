import { inject } from '@angular/core';
import { CanActivateFn } from '@angular/router';
import { forkJoin, map, of } from 'rxjs';

import { PermissionsService } from '../../services/auth/permissions.service';
import { ProfileService } from '../../services/auth/profile.service';

/**
 * Loads user profile + permissions. Always returns true.
 * Ensures all children have access to user data.
 */
export const bootstrapGuard: CanActivateFn = () => {
    const profileService = inject(ProfileService);
    const permissionsService = inject(PermissionsService);

    const cached = profileService.currentUserSignal();
    if (cached) {
        if (permissionsService.active() !== null || cached.memberships.length === 0) {
            permissionsService.loadCatalog().subscribe();
            return of(true);
        }
    }

    return forkJoin([profileService.bootstrapUser(), permissionsService.loadCatalog()]).pipe(map(() => true));
};
