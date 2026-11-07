import { HttpErrorResponse } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';

import { ToastService } from '../../services/notifications';
import { showHttpErrorToast } from './http-error-toast.util';

describe('showHttpErrorToast', () => {
    it.each([
        {
            case: "the backend's message after the heading",
            error: new HttpErrorResponse({
                status: 400,
                error: { error: 'Knowledge Retriever node "Search docs #1" needs a collection, a RAG and a query.' },
            }),
            message:
                'Couldn\'t run the flow. Knowledge Retriever node "Search docs #1" needs a collection, a RAG and a query.',
        },
        {
            case: 'the server failure message with its support reference',
            error: new HttpErrorResponse({
                status: 500,
                error: {
                    status_code: 500,
                    code: 'internal_error',
                    message:
                        'Something went wrong on the server. Try again or contact your administrator (reference: 3f9a2c1b7d4e).',
                    reference: '3f9a2c1b7d4e',
                },
            }),
            message:
                "Couldn't run the flow. Something went wrong on the server. Try again or contact your administrator (reference: 3f9a2c1b7d4e).",
        },
        {
            case: 'a plain sentence instead of the raw HTTP text when the server is unreachable',
            error: new HttpErrorResponse({ status: 0, url: 'http://localhost/api/run-session/' }),
            message: "Couldn't run the flow. The server couldn't be reached. Check your connection and try again.",
        },
        {
            case: 'a plain sentence instead of the raw HTTP text when the server failed without a message',
            error: new HttpErrorResponse({ status: 500, url: 'http://localhost/api/run-session/' }),
            message:
                "Couldn't run the flow. Something went wrong on the server. Try again or contact your administrator.",
        },
    ])('shows $case, in full and for longer than a default toast', async ({ error, message }) => {
        const toastService = new ToastService();

        showHttpErrorToast(toastService, "Couldn't run the flow.", error);

        const [toast] = await firstValueFrom(toastService.toasts$);
        expect(toast).toMatchObject({ message, type: 'error', duration: 10_000, fullText: true });
    });

    it('shows the toast where the caller asks', async () => {
        const toastService = new ToastService();
        toastService.setDefaultPosition('top-right');

        showHttpErrorToast(
            toastService,
            "Couldn't import the nodes.",
            new HttpErrorResponse({ status: 0 }),
            'bottom-right'
        );

        const [toast] = await firstValueFrom(toastService.toasts$);
        expect(toastService.getPositionForToast(toast.id)).toBe('bottom-right');
    });
});
