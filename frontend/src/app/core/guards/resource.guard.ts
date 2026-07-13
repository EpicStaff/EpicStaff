import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { AuthService } from '../../services/auth/auth.service';
import { PermissionsService } from '../../services/auth/permissions.service';
import { ProfileService } from '../../services/auth/profile.service';

/**
 * Access-check guard for MainLayoutComponent.
 * Assumes profile + permissions already loaded.
 */
export const resourceGuard: CanActivateFn = () => {
    const profileService = inject(ProfileService);
    const permissionsService = inject(PermissionsService);
    const router = inject(Router);

    const user = profileService.currentUserSignal();
    if (user && !user.is_superadmin && user.memberships.length === 0) {
        return router.parseUrl(permissionsService.resolveDefaultRoute());
    }
    return true;
};

/**
 * Reverse guard for /unassigned.
 * If the user has permissions (e.g. admin added them to an org), redirect away.
 */
export const unassignedGuard: CanActivateFn = () => {
    const permissionsService = inject(PermissionsService);
    const router = inject(Router);
    const resolved = permissionsService.resolveDefaultRoute();
    return resolved === '/unassigned' ? true : router.parseUrl(resolved);
};

/**
 * Only allows access when a default org was just created (sign-up flow).
 * Otherwise redirects to root and lets the guard chain resolve the destination.
 */
export const onboardingGuard: CanActivateFn = () => {
    const authService = inject(AuthService);
    const router = inject(Router);
    return authService.defaultOrgId() ? true : router.parseUrl('/');
};
