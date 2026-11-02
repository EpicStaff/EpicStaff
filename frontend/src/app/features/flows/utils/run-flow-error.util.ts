import { HttpErrorResponse } from '@angular/common/http';
import { extractHttpErrorMessage } from '@shared/utils';

import { ToastService } from '../../../services/notifications';

// A run error names the node and says how to fix it, so it is longer than most toasts.
const RUN_FLOW_ERROR_TOAST_DURATION_MS = 10_000;

// Status 0 means no response at all; without this the toast shows "Http failure response for …: 0 Unknown Error".
const SERVER_UNREACHABLE_MESSAGE = "The server couldn't be reached. Check your connection and try again.";

/**
 * Shows why a flow didn't start, in full: a clamped toast would cut off the part that says what to fix.
 * The heading is its own sentence; the backend message is appended unchanged.
 */
export function showRunFlowError(toastService: ToastService, heading: string, error: HttpErrorResponse): void {
    const reason = error.status === 0 ? SERVER_UNREACHABLE_MESSAGE : extractHttpErrorMessage(error);
    toastService.error(`${heading} ${reason}`, RUN_FLOW_ERROR_TOAST_DURATION_MS, undefined, { fullText: true });
}
