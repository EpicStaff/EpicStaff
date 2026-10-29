/** Mirrors the backend `MAX_TRIGGER_PAYLOAD_BYTES` (tables/constants/trigger_payload_constants.py). */
export const MAX_TRIGGER_PAYLOAD_BYTES = 1024 * 1024;

export type TriggerTestPayload = Record<string, unknown>;

export type TestPayloadParseResult = { value: TriggerTestPayload; error?: never } | { value?: never; error: string };

const NUL_CHARACTER = '\u0000';
const UNPAIRED_SURROGATE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/;

export function isPlainJsonObject(value: unknown): value is TriggerTestPayload {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * Parses the text of a test payload editor. The result is either a value the backend will accept
 * (`validate_trigger_payload`) or the reason it would not.
 */
export function parseTestPayload(text: string): TestPayloadParseResult {
    let parsed: unknown;
    try {
        parsed = JSON.parse(text);
    } catch (parseError) {
        const reason = parseError instanceof Error ? parseError.message : String(parseError);
        return { error: `Invalid JSON: ${reason}` };
    }
    const error = validateTestPayloadValue(parsed);
    return error === null ? { value: parsed as TriggerTestPayload } : { error };
}

/**
 * Applies the backend's rules to an already-parsed value: a JSON object, no NUL character or
 * unpaired surrogate in any key or string, and at most `MAX_TRIGGER_PAYLOAD_BYTES` as UTF-8
 * compact JSON (non-ASCII kept as-is, like the backend's `ensure_ascii=False`).
 */
export function validateTestPayloadValue(value: unknown): string | null {
    if (!isPlainJsonObject(value)) {
        return 'Test payload must be a JSON object.';
    }
    const invalidTextReason = findInvalidText(value);
    if (invalidTextReason !== null) {
        return invalidTextReason;
    }
    const encodedSize = new TextEncoder().encode(JSON.stringify(value)).length;
    if (encodedSize > MAX_TRIGGER_PAYLOAD_BYTES) {
        return `Test payload must not exceed ${MAX_TRIGGER_PAYLOAD_BYTES} bytes of compact JSON (got ${encodedSize}).`;
    }
    return null;
}

function findInvalidText(value: unknown): string | null {
    if (typeof value === 'string') {
        return describeInvalidString(value);
    }
    if (Array.isArray(value)) {
        for (const item of value) {
            const reason = findInvalidText(item);
            if (reason !== null) return reason;
        }
        return null;
    }
    if (isPlainJsonObject(value)) {
        for (const [key, item] of Object.entries(value)) {
            const reason = describeInvalidString(key) ?? findInvalidText(item);
            if (reason !== null) return reason;
        }
    }
    return null;
}

function describeInvalidString(text: string): string | null {
    if (text.includes(NUL_CHARACTER)) {
        return 'Test payload must not contain the NUL character (\\u0000) in any key or value.';
    }
    if (UNPAIRED_SURROGATE.test(text)) {
        return 'Test payload must not contain unpaired Unicode surrogates.';
    }
    return null;
}
