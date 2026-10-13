import { HttpErrorResponse } from '@angular/common/http';

/** Parses Retry-After, which is delay-seconds or an HTTP date. */
export function parseRetryAfterSeconds(header: string | null): number | null {
    if (!header) return null;
    const value = header.trim();
    if (/^\d+$/.test(value)) return Number(value);
    const date = Date.parse(value);
    if (Number.isNaN(date)) return null;
    return Math.max(0, Math.ceil((date - Date.now()) / 1000));
}

/** Seconds the server asked the client to wait, or null when the response carries no readable Retry-After. */
export function getRetryAfterSeconds(error: HttpErrorResponse): number | null {
    return parseRetryAfterSeconds(error.headers?.get('Retry-After') ?? null);
}
