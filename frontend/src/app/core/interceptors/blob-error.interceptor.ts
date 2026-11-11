import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { catchError, from, switchMap, throwError } from 'rxjs';

/**
 * Turns the Blob body of a failed download into the JSON the backend actually sent.
 *
 * A download asks for `responseType: 'blob'`, so Angular hands the error body over as a Blob
 * as well, and every reader in the app then finds an object with nothing in it and falls back
 * to "Http failure response". Read once here, before any other interceptor sees the error, so
 * a refused export tells the user why it was refused.
 */
export const blobErrorInterceptor: HttpInterceptorFn = (req, next) =>
    next(req).pipe(
        catchError((error: HttpErrorResponse) => {
            if (!(error.error instanceof Blob)) return throwError(() => error);
            return from(error.error.text()).pipe(
                // The unread body is no reason to replace the failure with another one.
                catchError(() => throwError(() => error)),
                switchMap((text) => throwError(() => withParsedBody(error, text)))
            );
        })
    );

function withParsedBody(error: HttpErrorResponse, text: string): HttpErrorResponse {
    let body: unknown = text;
    try {
        body = JSON.parse(text);
    } catch {
        // Not JSON -- the text itself is the most a reader can be given.
    }
    return new HttpErrorResponse({
        error: body,
        headers: error.headers,
        status: error.status,
        statusText: error.statusText,
        url: error.url ?? undefined,
    });
}
