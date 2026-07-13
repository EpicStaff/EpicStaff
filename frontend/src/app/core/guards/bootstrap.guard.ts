import { inject } from '@angular/core';
import { CanActivateFn } from '@angular/router';
import { map, of } from 'rxjs';

import { ProfileService } from '../../services/auth/profile.service';

/**
 * Loads user profile + permissions. Always returns true.
 * Ensures all children have access to user data.
 */
export const bootstrapGuard: CanActivateFn = () => {
    const profileService = inject(ProfileService);

    const cached = profileService.currentUserSignal();
    if (cached) {
        return of(true);
    }

    return profileService.bootstrapUser().pipe(map(() => true));
};
