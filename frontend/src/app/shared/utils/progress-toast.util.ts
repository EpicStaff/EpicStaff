import { defer, MonoTypeOperatorFunction } from 'rxjs';
import { finalize } from 'rxjs/operators';

import { ToastService } from '../../services/notifications';

/**
 * Shows `message` as an info toast from subscription until the source completes, fails or is unsubscribed.
 * `maxDurationMs` takes it down anyway, for a source that runs longer.
 */
export function withProgressToast<T>(
    toastService: ToastService,
    message: string,
    maxDurationMs: number
): MonoTypeOperatorFunction<T> {
    return (source) =>
        defer(() => {
            const toastId = toastService.show(message, 'info', maxDurationMs);
            return source.pipe(finalize(() => toastService.remove(toastId)));
        });
}
