import { HttpErrorResponse } from '@angular/common/http';

import { isGraphNotIndexedError } from './graph-not-indexed-error.util';

describe('isGraphNotIndexedError', () => {
    it.each<[string, number, unknown, boolean]>([
        ['409 graph_not_indexed', 409, { status_code: 409, code: 'graph_not_indexed', message: 'x' }, true],
        ['409 with another code', 409, { status_code: 409, code: 'upstream_resource_conflict', message: 'x' }, false],
        ['409 without a code', 409, { message: 'x' }, false],
        ['409 with a text body', 409, 'graph_not_indexed', false],
        ['409 with no body', 409, null, false],
        ['404 carrying the code', 404, { code: 'graph_not_indexed' }, false],
    ])('classifies %s', (_case, status, body, expected) => {
        const error = new HttpErrorResponse({ status, error: body });

        expect(isGraphNotIndexedError(error)).toBe(expected);
    });
});
