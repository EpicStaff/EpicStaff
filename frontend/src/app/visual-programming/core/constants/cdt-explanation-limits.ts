/**
 * Limits on a Classification Decision Table node's stored `metadata.explanations`.
 *
 * Mirrors `src/django_app/tables/constants/cdt_explanation_limits.py`: the explanations
 * endpoint refuses a map past them, and bulk save drops what does not fit. Keep the two
 * in step, or the frontend sends what the backend refuses.
 */
export const CDT_EXPLANATION_LIMITS = {
    maxEntries: 1000,
    /** Above 255 on purpose: a rule's key carries its `group_name`, which may be 255 characters. */
    maxStepKeyLength: 512,
    maxTextLength: 20_000,
    maxGeneratedByLength: 255,
    maxFingerprintLength: 128,
    /** The whole map as stored: compact JSON, UTF-8. */
    maxTotalBytes: 1024 * 1024,
} as const;
