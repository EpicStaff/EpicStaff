import { HttpErrorResponse, HttpHandlerFn, HttpInterceptorFn, HttpRequest } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, switchMap, throwError } from 'rxjs';

import { AuthService } from '../../services/auth/auth.service';

export const authInterceptor: HttpInterceptorFn = (req: HttpRequest<unknown>, next: HttpHandlerFn) => {
    const authService = inject(AuthService);
    const router = inject(Router);

    const isAuthEndpoint = req.url.includes('/auth/token/') || req.url.includes('/auth/token/refresh/');

    const access = authService.getAccessToken();
    const authReq = access && !isAuthEndpoint ? req.clone({ setHeaders: { Authorization: `Bearer ${access}` } }) : req;

    return next(authReq).pipe(
        catchError((err: HttpErrorResponse) => {
            if ((err.status !== 401 && err.status !== 403) || isAuthEndpoint) {
                return throwError(() => err);
            }

            return authService.refreshToken().pipe(
                switchMap((newAccess) => {
                    if (!newAccess) {
                        authService.logout();
                        void router.navigate(['/login']);
                        return throwError(() => err);
                    }
                    const retryReq = req.clone({
                        setHeaders: { Authorization: `Bearer ${newAccess}` },
                    });
                    return next(retryReq);
                }),
                catchError(() => {
                    authService.logout();
                    void router.navigate(['/login']);
                    return throwError(() => err);
                })
            );
        })
    );
};
