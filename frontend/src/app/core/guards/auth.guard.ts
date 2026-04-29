import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { catchError, map, of, switchMap } from 'rxjs';

import { AuthService } from '../../services/auth/auth.service';

export const authGuard: CanActivateFn = (route, state) => {
    const authService = inject(AuthService);
    const router = inject(Router);

    const redirectToLogin = () => {
        void router.navigate(['/login'], { queryParams: { returnUrl: state.url } });
        return of(false);
    };

    return authService.getStatus().pipe(
        switchMap((status) => {
            if (status.needs_setup) {
                void router.navigate(['/sign-up'], { queryParams: { returnUrl: state.url } });
                return of(false);
            }
            if (authService.isAuthenticated()) {
                return of(true);
            }
            // Access token expired or missing — try to refresh
            return authService.refreshToken().pipe(
                map((accessToken) => {
                    if (accessToken) return true;
                    void router.navigate(['/login'], { queryParams: { returnUrl: state.url } });
                    return false;
                }),
                catchError(() => redirectToLogin())
            );
        }),
        catchError(() => {
            if (authService.isAuthenticated()) {
                return of(true);
            }
            return redirectToLogin();
        })
    );
};
