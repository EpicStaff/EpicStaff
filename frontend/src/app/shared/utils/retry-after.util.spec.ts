import { HttpErrorResponse, HttpHeaders } from '@angular/common/http';

import { getRetryAfterSeconds, parseRetryAfterSeconds } from './retry-after.util';

describe('parseRetryAfterSeconds', () => {
    afterEach(() => vi.useRealTimers());

    it.each([
        { header: '58', expected: 58 },
        { header: ' 0 ', expected: 0 },
        { header: null, expected: null },
        { header: '', expected: null },
        { header: 'soon', expected: null },
    ])('reads "$header" as $expected', ({ header, expected }) => {
        expect(parseRetryAfterSeconds(header)).toBe(expected);
    });

    it('reads an HTTP date as the seconds left until it', () => {
        vi.useFakeTimers();
        vi.setSystemTime(new Date('2026-01-01T00:00:00Z'));

        expect(parseRetryAfterSeconds('Thu, 01 Jan 2026 00:01:30 GMT')).toBe(90);
        expect(parseRetryAfterSeconds('Wed, 31 Dec 2025 23:59:00 GMT')).toBe(0);
    });
});

describe('getRetryAfterSeconds', () => {
    it('reads the Retry-After header of an error response', () => {
        const error = new HttpErrorResponse({ status: 429, headers: new HttpHeaders({ 'Retry-After': '58' }) });

        expect(getRetryAfterSeconds(error)).toBe(58);
    });

    it('returns null when the header is absent', () => {
        expect(getRetryAfterSeconds(new HttpErrorResponse({ status: 429 }))).toBeNull();
    });
});
