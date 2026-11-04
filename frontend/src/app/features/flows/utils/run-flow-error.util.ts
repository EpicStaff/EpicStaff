import { HttpErrorResponse } from '@angular/common/http';
import { httpErrorReason } from '@shared/utils';

import { ToastService } from '../../../services/notifications';

// A run error names the node and says how to fix it, so it is longer than most toasts.
const RUN_FLOW_ERROR_TOAST_DURATION_MS = 10_000;

/**
 * Shows why a flow didn't start, in full: a clamped toast would cut off the part that says what to fix.
 * The heading is its own sentence; the backend message is appended unchanged.
 */
export function showRunFlowError(toastService: ToastService, heading: string, error: HttpErrorResponse): void {
    toastService.error(`${heading} ${httpErrorReason(error)}`, RUN_FLOW_ERROR_TOAST_DURATION_MS, undefined, {
        fullText: true,
    });
}
