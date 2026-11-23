import { HttpErrorResponse } from '@angular/common/http';

import { rbacErrorMessage } from './rbac-error-messages.util';

function failure(status: number, body: unknown): HttpErrorResponse {
    return new HttpErrorResponse({ status, error: body });
}

describe('rbacErrorMessage', () => {
    it.each([
        {
            case: 'the text of a known code, from a Django body',
            body: {
                type: 'client_error',
                errors: [{ code: 'last_superadmin', detail: 'Server text.', attr: null, context: null }],
            },
            expected: 'At least one active superadmin must remain.',
        },
        {
            case: 'the text of a known code, from an envelope',
            body: { type: 'client_error', errors: [{ code: 'last_superadmin', detail: 'Server text.', attr: null }] },
            expected: 'At least one active superadmin must remain.',
        },
        {
            case: "the server's message for an unknown code, from a Django body",
            body: {
                type: 'client_error',
                errors: [{ code: 'something_new', detail: 'The org is locked.', attr: null, context: null }],
            },
            expected: 'The org is locked.',
        },
        {
            case: "the server's detail for an unknown code, from an envelope",
            body: { type: 'client_error', errors: [{ code: 'something_new', detail: 'The org is locked.' }] },
            expected: 'The org is locked.',
        },
        {
            case: 'the fallback for a body without a message',
            body: { type: 'server_error', errors: [{ code: 'x', detail: '', attr: null, context: null }] },
            expected: 'Nope',
        },
        { case: 'the fallback for a body that is not JSON', body: 'Bad gateway', expected: 'Nope' },
    ])('gives $case', ({ body, expected }) => {
        expect(rbacErrorMessage(failure(409, body), 'Nope')).toBe(expected);
    });

    it('gives the fallback for a failure that is not an HTTP error', () => {
        expect(rbacErrorMessage(new Error('boom'), 'Nope')).toBe('Nope');
    });
});
