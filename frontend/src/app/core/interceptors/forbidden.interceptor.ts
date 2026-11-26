import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, concatWith, throwError } from 'rxjs';

import { CurrentUserRefreshService } from '../../services/auth/current-user-refresh.service';
import { wasHandledByForbiddenInterceptor } from './forbidden-interceptor-handled.util';

/**
 * Hands a 403 that may mean the user's access changed to `CurrentUserRefreshService` (a toast, a reload of the
 * user, a re-entry of the current page), then passes the error on once that is done. The caller stays quiet
 * (`wasHandledByForbiddenInterceptor`).
 */
export const forbiddenInterceptor: HttpInterceptorFn = (req, next) => {
    const currentUserRefresh = inject(CurrentUserRefreshService);

    return next(req).pipe(
        catchError((err: HttpErrorResponse) => {
            if (!wasHandledByForbiddenInterceptor(err, req.context)) {
                return throwError(() => err);
            }
            return currentUserRefresh.handleForbidden(req, err).pipe(concatWith(throwError(() => err)));
        })
    );
};
