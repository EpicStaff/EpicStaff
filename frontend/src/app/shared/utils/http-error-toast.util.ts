import { HttpErrorResponse } from '@angular/common/http';

import { ToastPosition, ToastService } from '../../services/notifications';
import { httpErrorReason } from './http-error-reason.util';

// The reason can say what to fix or end with the reference the user quotes to support, so it gets time to be read.
const HTTP_ERROR_TOAST_DURATION_MS = 10_000;

/**
 * Shows why a request failed, in full: "<heading> <reason>". A clamped toast would cut off the end of the reason —
 * what to fix, or the support reference.
 * The heading is its own sentence, e.g. "Couldn't save the flow."; the reason comes from `httpErrorReason`.
 */
export function showHttpErrorToast(
    toastService: ToastService,
    heading: string,
    error: HttpErrorResponse | Error,
    position?: ToastPosition
): void {
    toastService.error(`${heading} ${httpErrorReason(error)}`, HTTP_ERROR_TOAST_DURATION_MS, position, {
        fullText: true,
    });
}
