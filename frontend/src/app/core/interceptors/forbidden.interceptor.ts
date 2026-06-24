import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, finalize, Observable, of, shareReplay, switchMap, tap, throwError } from 'rxjs';

import { ProfileService } from '../../services/auth/profile.service';

let refresh$: Observable<unknown> | null = null;

export const forbiddenInterceptor: HttpInterceptorFn = (req, next) => {
    const profileService = inject(ProfileService);
    const router = inject(Router);

    return next(req).pipe(
        catchError((err: HttpErrorResponse) => {
            if (err.status !== 403) {
                return throwError(() => err);
            }
            if (!refresh$) {
                profileService.clearCurrentUser();
                refresh$ = profileService.bootstrapUser().pipe(
                    tap(() => {
                        const currentUrl = router.url;
                        void router.navigateByUrl('/profile', { skipLocationChange: true }).then(() => {
                            void router.navigateByUrl(currentUrl);
                        });
                    }),
                    catchError(() => of(undefined)),
                    shareReplay(1),
                    finalize(() => (refresh$ = null))
                );
            }

            return refresh$.pipe(switchMap(() => throwError(() => err)));
        })
    );
};
