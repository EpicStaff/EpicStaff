import { FormControl } from '@angular/forms';

import { httpUrlValidator } from './http-url.validator';

function errorsFor(value: unknown) {
    return httpUrlValidator()(new FormControl(value));
}

describe('httpUrlValidator', () => {
    it.each([
        'http://mcp-server:8000/sse',
        'https://mcp.example.com/sse',
        'http://localhost',
        '  https://example.com/path  ',
    ])('accepts %s', (value) => {
        expect(errorsFor(value)).toBeNull();
    });

    it.each([
        '/tmp/server.py',
        'server.js',
        'stdio',
        'file:///etc/passwd',
        'ftp://example.com',
        'HTTPS://Example.com',
        'http:host',
        'http:///path',
        'https://',
    ])('rejects %s', (value) => {
        expect(errorsFor(value)).toEqual({ httpUrl: true });
    });

    it('leaves empty values to the required validator', () => {
        expect(errorsFor('')).toBeNull();
        expect(errorsFor(null)).toBeNull();
    });
});
