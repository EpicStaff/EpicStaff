import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { extractServerMessage } from '@shared/utils';
import { catchError, finalize, Observable, shareReplay, switchMap, tap, throwError } from 'rxjs';

import { ProfileService } from '../../services/auth/profile.service';
import { ToastService } from '../../services/notifications';
import { wasHandledByForbiddenInterceptor } from './forbidden-interceptor-handled.util';

let refresh$: Observable<unknown> | null = null;

export const forbiddenInterceptor: HttpInterceptorFn = (req, next) => {
    const profileService = inject(ProfileService);
    const router = inject(Router);
    const toast = inject(ToastService);

    return next(req).pipe(
        catchError((err: HttpErrorResponse) => {
            if (!wasHandledByForbiddenInterceptor(err, req.context)) {
                return throwError(() => err);
            }
            // A refused download's Blob body has already been parsed by blobErrorInterceptor, which runs first.
            toast.error(extractServerMessage(err) ?? 'Forbidden');
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
