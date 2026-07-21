/**
 * Generates an RFC-4122 v4 UUID string.
 * Uses `crypto.randomUUID()` when available, falling back to a manual
 * v4 UUID built from `crypto.getRandomValues()`, and finally to a pure
 * `Math.random()`-based generator when no `crypto` API is present at all.
 */
export function generateUuid(): string {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
        return crypto.randomUUID();
    }

    if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
        const bytes = crypto.getRandomValues(new Uint8Array(16));
        bytes[6] = (bytes[6] & 0x0f) | 0x40;
        bytes[8] = (bytes[8] & 0x3f) | 0x80;

        const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
        return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
    }

    // Final fallback: no `crypto` API at all, use Math.random().
    let uuid = '';
    for (let i = 0; i < 36; i++) {
        if (i === 8 || i === 13 || i === 18 || i === 23) {
            uuid += '-';
        } else if (i === 14) {
            uuid += '4';
        } else if (i === 19) {
            uuid += (((Math.random() * 4) | 0) + 8).toString(16);
        } else {
            uuid += ((Math.random() * 16) | 0).toString(16);
        }
    }
    return uuid;
}
