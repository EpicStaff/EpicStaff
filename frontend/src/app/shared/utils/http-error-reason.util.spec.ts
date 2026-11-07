import { HttpErrorResponse } from '@angular/common/http';

import { httpErrorReason } from './http-error-reason.util';

describe('httpErrorReason', () => {
    it.each([
        {
            case: 'no response at all',
            error: new HttpErrorResponse({ status: 0, url: 'http://localhost/api/graphs/1/' }),
            reason: "The server couldn't be reached. Check your connection and try again.",
        },
        {
            case: 'a message in the envelope',
            error: new HttpErrorResponse({ status: 409, error: { status_code: 409, message: 'The flow changed.' } }),
            reason: 'The flow changed.',
        },
        {
            case: 'a detail',
            error: new HttpErrorResponse({ status: 404, error: { detail: 'Not found.' } }),
            reason: 'Not found.',
        },
        {
            case: 'an error',
            error: new HttpErrorResponse({ status: 500, error: { error: 'Database unavailable.' } }),
            reason: 'Database unavailable.',
        },
        {
            case: 'a server error with no body',
            error: new HttpErrorResponse({ status: 500, url: 'http://localhost/api/graphs/1/' }),
            reason: 'Something went wrong on the server. Try again or contact your administrator.',
        },
        {
            case: 'a server error page instead of a message',
            error: new HttpErrorResponse({ status: 502, error: '<html><body>Bad Gateway</body></html>' }),
            reason: 'Something went wrong on the server. Try again or contact your administrator.',
        },
        {
            case: "the backend's answer to an error it didn't expect, with the reference for support",
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
            reason: 'Something went wrong on the server. Try again or contact your administrator (reference: 3f9a2c1b7d4e).',
        },
        {
            case: "a gateway service's error envelope, with the reference for support",
            error: new HttpErrorResponse({
                status: 500,
                error: {
                    type: 'server_error',
                    errors: [
                        {
                            code: 'internal_error',
                            detail: 'Something went wrong on the server. Try again or contact your administrator (reference: 3f9a2c1b7d4e).',
                            attr: null,
                        },
                    ],
                    reference: '3f9a2c1b7d4e',
                },
            }),
            reason: 'Something went wrong on the server. Try again or contact your administrator (reference: 3f9a2c1b7d4e).',
        },
        {
            case: 'a refused request with no message in its body',
            error: new HttpErrorResponse({ status: 400, url: 'http://localhost/api/graphs/1/', error: {} }),
            reason: 'The server rejected the request.',
        },
    ])('reads $case', ({ error, reason }) => {
        expect(httpErrorReason(error)).toBe(reason);
    });

    it('gives a plain sentence for an error thrown on the way, which has no status, and keeps its message out', () => {
        const thrown = new TypeError('Cannot read properties of undefined');
        const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);

        expect(httpErrorReason(thrown)).toBe('Something went wrong. Try again.');

        consoleError.mockRestore();
    });
});
