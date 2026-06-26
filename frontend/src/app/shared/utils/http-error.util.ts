import { HttpErrorResponse } from '@angular/common/http';

/**
 * Extracts a human-readable message from an HttpErrorResponse
 */

export function extractHttpErrorMessage(err: HttpErrorResponse): string {
    // Structured validation errors attached by validationErrorsInterceptor.
    if (Array.isArray(err.validationErrors) && err.validationErrors.length > 0) {
        const reasons = err.validationErrors.map((e) => e.reason).filter(Boolean);
        if (reasons.length) return joinErrorMessages(reasons);
    }

    const body = err?.error;
    if (body) {
        if (typeof body === 'string') return body;

        // Nested DRF validation errors (object), e.g.
        // { errors: { <node>_list: [ { index, errors: { prompt_configs: [ {}, { result_variable: ["..."] } ] } } ] } }
        if (body.errors != null) {
            const collected = collectValidationMessages(body.errors);
            if (collected.length) return joinErrorMessages(collected);
        }

        if (typeof body.message === 'string' && body.message) return body.message;
        if (typeof body.detail === 'string' && body.detail) return body.detail;
        if (typeof body.error === 'string' && body.error) return body.error;

        // Last resort: walk the whole body for field-level messages
        // (covers a bare { field: ["msg"] } DRF shape with no top-level wrapper).
        const collected = collectValidationMessages(body);
        if (collected.length) return joinErrorMessages(collected);
    }

    return err?.message || 'Unknown error';
}

/**
 * Recursively walks a (possibly deeply nested) DRF validation-error structure
 */

function collectValidationMessages(node: unknown): string[] {
    const out: string[] = [];

    const isNodeWrapper = (v: unknown): v is { index: unknown; errors: unknown } =>
        v != null && typeof v === 'object' && !Array.isArray(v) && 'errors' in v && 'index' in v;

    const append = (base: string, seg: string): string => (base ? `${base} → ${seg}` : seg);

    const walk = (value: unknown, p: string): void => {
        if (value == null) return;

        if (isNodeWrapper(value)) {
            walk(value.errors, p);
            return;
        }

        if (typeof value === 'string') {
            if (value.trim()) out.push(p ? `${p}: ${value}` : value);
            return;
        }

        if (Array.isArray(value)) {
            const allStrings = value.length > 0 && value.every((v) => typeof v === 'string');
            if (allStrings) {
                for (const s of value as string[]) walk(s, p);
            } else {
                value.forEach((el, i) => {
                    if (isNodeWrapper(el)) {
                        walk(el, p);
                    } else {
                        walk(el, p ? `${p}[${i}]` : `[${i}]`);
                    }
                });
            }
            return;
        }

        if (typeof value === 'object') {
            const obj = value as Record<string, unknown>;
            const keys = Object.keys(obj);

            if (keys.length === 1 && keys[0] === 'errors') {
                walk(obj['errors'], p);
                return;
            }

            for (const key of keys) {
                const child = obj[key];
                if (Array.isArray(child) && child.some(isNodeWrapper)) {
                    walk(child, p);
                } else {
                    walk(child, append(p, key));
                }
            }
            return;
        }
    };

    walk(node, '');
    return out;
}

/** Dedupe messages, cap to 3, and append "…and N more" for the remainder. */
function joinErrorMessages(messages: string[]): string {
    const unique = Array.from(new Set(messages));
    const MAX = 3;
    if (unique.length <= MAX) return unique.join('; ');
    return `${unique.slice(0, MAX).join('; ')}; …and ${unique.length - MAX} more`;
}
