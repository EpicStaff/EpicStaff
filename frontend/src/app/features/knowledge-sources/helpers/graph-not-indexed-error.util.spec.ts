import { HttpErrorResponse } from '@angular/common/http';

import { isGraphNotIndexedError } from './graph-not-indexed-error.util';

describe('isGraphNotIndexedError', () => {
    it.each<[string, number, unknown, boolean]>([
        [
            '409 graph_not_indexed',
            409,
            { type: 'client_error', errors: [{ code: 'graph_not_indexed', detail: 'x', attr: null }] },
            true,
        ],
        [
            '409 with another code',
            409,
            {
                type: 'client_error',
                errors: [{ code: 'upstream_resource_conflict', detail: 'x', attr: null, context: null }],
            },
            false,
        ],
        [
            '409 without a code',
            409,
            { type: 'client_error', errors: [{ code: 'unknown', detail: 'x', attr: null }] },
            false,
        ],
        ['409 with a text body', 409, 'graph_not_indexed', false],
        ['409 with no body', 409, null, false],
        [
            '404 carrying the code',
            404,
            { type: 'client_error', errors: [{ code: 'graph_not_indexed', detail: 'x', attr: null }] },
            false,
        ],
    ])('classifies %s', (_case, status, body, expected) => {
        const error = new HttpErrorResponse({ status, error: body });

        expect(isGraphNotIndexedError(error)).toBe(expected);
    });
});
