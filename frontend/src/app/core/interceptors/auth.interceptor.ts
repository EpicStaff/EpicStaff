import { HttpErrorResponse, HttpHandlerFn, HttpInterceptorFn, HttpRequest } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, switchMap, throwError } from 'rxjs';

import { AuthService } from '../../services/auth/auth.service';
import { SKIP_AUTH_HEADER_OVERRIDE } from './skip-auth-header-override.context';

export const authInterceptor: HttpInterceptorFn = (req: HttpRequest<unknown>, next: HttpHandlerFn) => {
    const authService = inject(AuthService);

    const isAuthEndpoint = req.url.includes('/auth/login/') || req.url.includes('/auth/refresh/');
    const skipOverride = req.context.get(SKIP_AUTH_HEADER_OVERRIDE);

    const access = authService.getAccessToken();
    const authReq =
        access && !isAuthEndpoint && !skipOverride
            ? req.clone({ setHeaders: { Authorization: `Bearer ${access}` } })
            : req;

    return next(authReq).pipe(
        catchError((err: HttpErrorResponse) => {
            if (err.status !== 401 || isAuthEndpoint || skipOverride) {
                return throwError(() => err);
            }

            return authService.refreshToken().pipe(
                switchMap((newAccess) => {
                    if (!newAccess) {
                        authService.removeTokenAndNavToLogin();
                        return throwError(() => err);
                    }
                    const retryReq = req.clone({
                        setHeaders: { Authorization: `Bearer ${newAccess}` },
                    });
                    return next(retryReq);
                }),
                catchError(() => throwError(() => err))
            );
        })
    );
};
