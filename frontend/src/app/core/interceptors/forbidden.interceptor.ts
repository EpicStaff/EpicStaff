import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, finalize, Observable, shareReplay, tap, throwError } from 'rxjs';
import { switchMap } from 'rxjs/operators';

import { ProfileService } from '../../services/auth/profile.service';
import { ToastService } from '../../services/notifications';
import { SKIP_FORBIDDEN_RELOAD } from './skip-forbidden-reload.context';

let refresh$: Observable<unknown> | null = null;

/**
 * Error codes for a 403 that reflects a fixed business rule on the targeted row (e.g.
 * "this specific row can't be edited"), not a change in the caller's own permissions.
 * These must not trigger the session refresh/reload below — the caller's own error
 * handling shows the message instead.
 */
const BUSINESS_RULE_FORBIDDEN_CODES = new Set<string>(['built_in_model_immutable']);

export const forbiddenInterceptor: HttpInterceptorFn = (req, next) => {
    const profileService = inject(ProfileService);
    const router = inject(Router);
    const toast = inject(ToastService);

    return next(req).pipe(
        catchError((err: HttpErrorResponse) => {
            if (
                err.status !== 403 ||
                req.context.get(SKIP_FORBIDDEN_RELOAD) ||
                BUSINESS_RULE_FORBIDDEN_CODES.has(err.error?.code)
            ) {
                return throwError(() => err);
            }
            toast.error(err.error.message);
            if (!refresh$) {
                profileService.clearCurrentUser();
                refresh$ = profileService.bootstrapUser().pipe(
                    tap(() => {
                        const currentUrl = router.url;

                        void router
                            .navigateByUrl('/profile', { skipLocationChange: true })
                            .then(() => void router.navigateByUrl(currentUrl));
                    }),
                    catchError(() => throwError(() => err)),
                    finalize(() => (refresh$ = null)),
                    shareReplay(1)
                );
            }

            return refresh$.pipe(switchMap(() => throwError(() => err)));
        })
    );
};
