import { AbstractControl, ValidationErrors, ValidatorFn } from '@angular/forms';

// Mirrors the backend check: lowercase http:// or https:// prefix (fastmcp matches it case-sensitively) and a non-empty host.
// `new URL()` is deliberately not used: it accepts `http:host` and rejects values the backend stores.
const HTTP_URL_PATTERN = /^https?:\/\/[^/?#]+/;

/**
 * Accepts only http(s) URLs with a host; single-label hosts like `http://mcp-server:8000/sse` are valid.
 * @returns `{ httpUrl: true }` if invalid, otherwise `null`. Empty values are left to `Validators.required`.
 */
export function httpUrlValidator(): ValidatorFn {
    return (control: AbstractControl): ValidationErrors | null => {
        const value: unknown = control.value;
        if (value === null || value === undefined || value === '') return null;
        if (typeof value !== 'string') return { httpUrl: true };
        return HTTP_URL_PATTERN.test(value.trim()) ? null : { httpUrl: true };
    };
}
