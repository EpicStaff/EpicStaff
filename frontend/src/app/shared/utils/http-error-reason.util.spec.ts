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
            case: 'a refused request with no message in its body',
            error: new HttpErrorResponse({ status: 400, url: 'http://localhost/api/graphs/1/', error: {} }),
            reason: 'The server rejected the request.',
        },
    ])('reads $case', ({ error, reason }) => {
        expect(httpErrorReason(error)).toBe(reason);
    });

    it('keeps the message of an error thrown on the way, which has no status', () => {
        const thrown = new TypeError('Cannot read properties of undefined');

        expect(httpErrorReason(thrown)).toBe('Cannot read properties of undefined');
    });
});
