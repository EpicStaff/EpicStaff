const ALLOWED_ORIGIN_ERROR = 'Use scheme and host only, e.g. https://www.example.com';

/** An origin as the chat service compares it: stripped, without a trailing slash, lower-cased. */
export function normalizeOrigin(value: string): string {
    return value.trim().replace(/\/$/, '').toLowerCase();
}

/**
 * Why an allowed origin would never match, or null when it can. The chat service compares a visitor's `Origin` header
 * with each allowed origin, both stripped, without a trailing slash and lower-cased; a browser sends scheme, host and a
 * non-default port only. So a path, a query, user info, a default port or a missing scheme never matches, while upper
 * case and one trailing slash do.
 */
export function allowedOriginError(value: string): string | null {
    const typed = normalizeOrigin(value);
    let url: URL;
    try {
        url = new URL(value);
    } catch {
        return ALLOWED_ORIGIN_ERROR;
    }
    const isWeb = url.protocol === 'http:' || url.protocol === 'https:';
    return isWeb && url.origin === typed ? null : ALLOWED_ORIGIN_ERROR;
}
