import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { catchError, map, of } from 'rxjs';

import { AuthService } from '../../services/auth/auth.service';
import { SetupService } from '../../services/auth/setup.service';

export const authGuard: CanActivateFn = (route, state) => {
    const authService = inject(AuthService);
    const setupService = inject(SetupService);
    const router = inject(Router);

    return setupService.getStatus().pipe(
        map((status) => {
            if (status.needs_setup) {
                void router.navigate(['/sign-up'], { queryParams: { returnUrl: state.url } });
                return false;
            }
            if (authService.isAuthenticated()) {
                return true;
            }
            void router.navigate(['/login'], { queryParams: { returnUrl: state.url } });
            return false;
        }),
        catchError(() => {
            if (authService.isAuthenticated()) {
                return of(true);
            }
            void router.navigate(['/login'], { queryParams: { returnUrl: state.url } });
            return of(false);
        })
    );
};
