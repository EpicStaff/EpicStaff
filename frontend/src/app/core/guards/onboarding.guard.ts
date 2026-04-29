import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { AuthService } from '../../services/auth/auth.service';

// TODO need update in future to check whether user completed onboarding or not
export const onboardingGuard: CanActivateFn = () => {
    const authService = inject(AuthService);
    const router = inject(Router);

    if (!authService.isAuthenticated()) {
        void router.navigate(['/login']);
        return false;
    }

    if (sessionStorage.getItem('needs_onboarding') !== 'true') {
        void router.navigate(['/projects']);
        return false;
    }

    return true;
};
