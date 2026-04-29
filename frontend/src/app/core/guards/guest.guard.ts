import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { catchError, map, of } from 'rxjs';

import { AuthService } from '../../services/auth/auth.service';

export const guestGuard: CanActivateFn = () => {
    const authService = inject(AuthService);
    const router = inject(Router);

    return authService.getStatus().pipe(
        map((status) => {
            // Always allow access during first-time setup regardless of auth state
            if (status.needs_setup) return true;
            if (authService.isAuthenticated()) {
                router.navigate(['/']);
                return false;
            }
            return true;
        }),
        catchError(() => {
            if (authService.isAuthenticated()) {
                router.navigate(['/']);
                return of(false);
            }
            return of(true);
        })
    );
};
