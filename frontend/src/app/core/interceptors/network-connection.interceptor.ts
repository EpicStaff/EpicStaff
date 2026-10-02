import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { throwError } from 'rxjs';
import { catchError } from 'rxjs/operators';

export const networkConnectionInterceptor: HttpInterceptorFn = (req, next) => {
    return next(req).pipe(
        catchError((err: unknown) => {
            if (!(err instanceof HttpErrorResponse) || err.status !== 0) {
                return throwError(() => err);
            }

            const normalized = new HttpErrorResponse({
                error: { message: 'You appear to be offline. Please check your internet connection.' },
                headers: err.headers,
                status: err.status,
                statusText: err.statusText || 'Network Error',
                url: err.url ?? undefined,
            });
            return throwError(() => normalized);
        })
    );
};
