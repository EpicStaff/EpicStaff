import { HttpErrorResponse } from '@angular/common/http';

import { extractHttpErrorMessage } from './http-error.util';

function errorResponse(status: number, body: unknown): HttpErrorResponse {
    return new HttpErrorResponse({ status, error: body, url: 'http://api.test/venvs/' });
}

describe('extractHttpErrorMessage', () => {
    it.each([
        [500, '<!DOCTYPE html>\n<html><body>ProgrammingError at /venvs/</body></html>', 'Server error (500)'],
        [502, '  <html><body>Bad Gateway</body></html>', 'Server error (502)'],
        [404, '<!doctype html><title>Not Found</title>', 'Request failed (404)'],
    ])('never shows an HTML page as the message (status %i)', (status, body, expected) => {
        expect(extractHttpErrorMessage(errorResponse(status, body))).toBe(expected);
    });

    it('uses the caller fallback instead of an HTML page when one is given', () => {
        expect(extractHttpErrorMessage(errorResponse(500, '<!DOCTYPE html><html></html>'), 'Could not save')).toBe(
            'Could not save'
        );
    });

    it('still shows a plain-text body', () => {
        expect(extractHttpErrorMessage(errorResponse(400, 'Name is taken'))).toBe('Name is taken');
    });

    it('shows the details of an errors envelope, deduplicated', () => {
        const body = {
            type: 'server_error',
            errors: [
                { code: 'unknown', detail: 'invalid input for query argument $6' },
                { code: 'unknown', detail: 'invalid input for query argument $6' },
                { code: 'invalid', detail: 'Version does not satisfy specification' },
            ],
        };

        expect(extractHttpErrorMessage(errorResponse(500, body))).toBe(
            'invalid input for query argument $6; Version does not satisfy specification'
        );
    });

    it('keeps the field path for nested validation errors', () => {
        const body = { errors: { name: ['This field is required.'] } };

        expect(extractHttpErrorMessage(errorResponse(400, body))).toBe('name: This field is required.');
    });
});
