import { HttpErrorResponse } from '@angular/common/http';

import type { ToastService } from '../../services/notifications/toast.service';
import { extractHttpErrorMessage } from './http-error.util';

/**
 * Writes text to the clipboard. Text that is still loading goes in as a promised `ClipboardItem`, written
 * inside the click or key press that asked for it: Safari refuses a clipboard write that starts after an await.
 * Browsers without `ClipboardItem` get `writeText` once the text is there. Rejects (never throws) when there is
 * no clipboard, e.g. on a non-secure origin.
 */
export async function writeClipboardText(text: string | Promise<string>): Promise<void> {
    if (typeof text === 'string') return navigator.clipboard.writeText(text);
    // Nothing is awaited before this write, so it still runs inside the user's gesture.
    if (typeof ClipboardItem !== 'undefined' && navigator.clipboard?.write) {
        const blob = text.then((value) => new Blob([value], { type: 'text/plain' }));
        return navigator.clipboard.write([new ClipboardItem({ 'text/plain': blob })]);
    }
    const value = await text;
    return navigator.clipboard.writeText(value);
}

/**
 * Copies with the app's toasts. When loading the text fails with an HTTP error (e.g. a 404 for an entry deleted
 * meanwhile), the toast gives the server's reason; any other failure reads "Failed to copy".
 */
export function copyWithFeedback(text: string | Promise<string>, toastService: ToastService): Promise<void> {
    let loadError: unknown = null;
    const guarded =
        typeof text === 'string'
            ? text
            : text.catch((error: unknown) => {
                  loadError = error;
                  throw error;
              });
    return writeClipboardText(guarded).then(
        () => toastService.success('Copied to clipboard!', 3000, 'bottom-right'),
        () =>
            toastService.error(
                loadError instanceof HttpErrorResponse ? extractHttpErrorMessage(loadError) : 'Failed to copy',
                3000,
                'top-right'
            )
    );
}
