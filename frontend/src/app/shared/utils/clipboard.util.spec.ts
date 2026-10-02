import { HttpErrorResponse } from '@angular/common/http';

import type { ToastService } from '../../services/notifications/toast.service';
import { copyWithFeedback, writeClipboardText } from './clipboard.util';

describe('writeClipboardText', () => {
    afterEach(() => {
        vi.unstubAllGlobals();
        Reflect.deleteProperty(navigator, 'clipboard');
    });

    it('writes promised text as a ClipboardItem at once where supported', async () => {
        const write = vi.fn(() => Promise.resolve());
        const items: Record<string, Promise<Blob>>[] = [];
        vi.stubGlobal(
            'ClipboardItem',
            class {
                constructor(data: Record<string, Promise<Blob>>) {
                    items.push(data);
                }
            }
        );
        Object.defineProperty(navigator, 'clipboard', { value: { write, writeText: vi.fn() }, configurable: true });

        await writeClipboardText(Promise.resolve('later'));

        expect(write).toHaveBeenCalledOnce();
        expect(await (await items[0]['text/plain']).text()).toBe('later');
    });

    it('falls back to writeText once the text is there', async () => {
        const writeText = vi.fn(() => Promise.resolve());
        Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });

        await writeClipboardText(Promise.resolve('later'));
        await writeClipboardText('now');

        expect(writeText.mock.calls).toEqual([['later'], ['now']]);
    });

    it('rejects instead of throwing when there is no clipboard (a non-secure origin)', async () => {
        Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true });
        let result: Promise<void> | undefined;
        expect(() => (result = writeClipboardText('text'))).not.toThrow();
        await expect(result).rejects.toBeInstanceOf(TypeError);
        await expect(writeClipboardText(Promise.resolve('later'))).rejects.toBeInstanceOf(TypeError);
    });
});

describe('copyWithFeedback', () => {
    afterEach(() => Reflect.deleteProperty(navigator, 'clipboard'));

    function toasts() {
        return { success: vi.fn(), error: vi.fn() };
    }

    it('confirms a copy', async () => {
        Object.defineProperty(navigator, 'clipboard', {
            value: { writeText: () => Promise.resolve() },
            configurable: true,
        });
        const toast = toasts();
        await copyWithFeedback('text', toast as unknown as ToastService);
        expect(toast.success).toHaveBeenCalledWith('Copied to clipboard!', 3000, 'bottom-right');
    });

    it("gives the server's reason when loading the text failed", async () => {
        Object.defineProperty(navigator, 'clipboard', { value: { writeText: vi.fn() }, configurable: true });
        const toast = toasts();
        const notFound = new HttpErrorResponse({ status: 404, error: { message: 'Entry not found.' } });
        await copyWithFeedback(Promise.reject(notFound), toast as unknown as ToastService);
        expect(toast.error).toHaveBeenCalledWith('Entry not found.', 3000, 'top-right');
    });

    it('reads "Failed to copy" for any other failure', async () => {
        Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true });
        const toast = toasts();
        await copyWithFeedback('text', toast as unknown as ToastService);
        expect(toast.error).toHaveBeenCalledWith('Failed to copy', 3000, 'top-right');
    });
});
