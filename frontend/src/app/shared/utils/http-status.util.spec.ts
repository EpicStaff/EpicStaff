import { HttpErrorResponse } from '@angular/common/http';

import { isClientError } from './http-status.util';

describe('isClientError', () => {
    it.each([
        [0, false],
        [399, false],
        [400, true],
        [403, true],
        [499, true],
        [500, false],
        [503, false],
    ])('status %i -> %s', (status, expected) => {
        expect(isClientError(new HttpErrorResponse({ status }))).toBe(expected);
    });
});
