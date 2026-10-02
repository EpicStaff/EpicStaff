/**
 * The `explanations` entry of a Classification Decision Table node's `metadata`.
 *
 * `metadata` is free-form JSON that no serializer validates, so entries are checked
 * field by field rather than trusted. Keys go out sorted because the save diff
 * compares stringified snapshots — an unsorted map would come back in another order
 * and make the node look edited on every reload.
 */

import { CdtExplanation, CdtExplanations } from '../core/models/classification-decision-table.model';

const METADATA_KEY = 'explanations';

/** Whatever the server sent, reduced to the entries that are actually usable. */
export function readCdtExplanations(metadata: Record<string, unknown> | null | undefined): CdtExplanations {
    const raw = metadata?.[METADATA_KEY];
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};

    const explanations: Record<string, CdtExplanation> = {};
    for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
        const explanation = toExplanation(value);
        if (explanation) explanations[key] = explanation;
    }

    return explanations;
}

/**
 * The value to put under `metadata.explanations`. Normalized to `{}` rather than
 * omitted, so a node never explained and one whose explanations were all dropped
 * stringify identically.
 */
export function toStoredCdtExplanations(explanations: CdtExplanations | undefined): Record<string, CdtExplanation> {
    const source = explanations ?? {};
    const stored: Record<string, CdtExplanation> = {};

    for (const key of Object.keys(source).sort()) {
        const { text, fingerprint, generatedBy } = source[key];
        stored[key] = { text, fingerprint, generatedBy };
    }

    return stored;
}

function toExplanation(value: unknown): CdtExplanation | null {
    if (!value || typeof value !== 'object') return null;

    const { text, fingerprint, generatedBy } = value as {
        text?: unknown;
        fingerprint?: unknown;
        generatedBy?: unknown;
    };
    if (typeof text !== 'string' || typeof fingerprint !== 'string' || typeof generatedBy !== 'string') {
        return null;
    }

    return { text, fingerprint, generatedBy };
}
