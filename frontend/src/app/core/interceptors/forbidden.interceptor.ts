import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, EMPTY, finalize, Observable, of, shareReplay, tap, throwError } from 'rxjs';
import { switchMap } from 'rxjs/operators';

import { ProfileService } from '../../services/auth/profile.service';
import { ToastService } from '../../services/notifications';

let refresh$: Observable<unknown> | null = null;

export const forbiddenInterceptor: HttpInterceptorFn = (req, next) => {
    const profileService = inject(ProfileService);
    const router = inject(Router);
    const toast = inject(ToastService);

    return next(req).pipe(
        catchError((err: HttpErrorResponse) => {
            if (err.status !== 403) {
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
                    catchError(() => of(undefined)),
                    finalize(() => (refresh$ = null)),
                    shareReplay(1)
                );
            }

            return refresh$.pipe(switchMap(() => EMPTY));
        })
    );
};
