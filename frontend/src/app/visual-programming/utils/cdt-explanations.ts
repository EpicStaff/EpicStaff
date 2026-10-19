/**
 * The `explanations` entry of a Classification Decision Table node's `metadata`.
 *
 * The backend validates these with the rules in `CDT_EXPLANATION_LIMITS`: the
 * explanations endpoint refuses a map that breaks them, and bulk save, node
 * create/update and import drop the entries that do. Entries read back are still
 * checked field by field — graphs saved before that may hold anything. Keys go out
 * sorted because the save diff compares stringified snapshots — an unsorted map
 * would come back in another order and make the node look edited on every reload.
 */

import { CDT_EXPLANATION_LIMITS } from '../core/constants/cdt-explanation-limits';
import { CdtExplanation, CdtExplanations } from '../core/models/classification-decision-table.model';

const METADATA_KEY = 'explanations';

/** A NUL or an unpaired surrogate: refused by the backend's string fields and by Postgres JSON. */
const UNSTORABLE_CHARACTER = /\0|[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/;

const UTF8 = new TextEncoder();

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
 * The value to put under `metadata.explanations`: what the backend will store, by
 * its own rule (`select_storable_explanations`), so neither the explanations
 * endpoint nor a full save refuses or trims what the editor holds.
 *
 * Entries are taken in step-key order. One the backend would refuse — a key or a
 * field empty, too long, or holding a character it rejects — is skipped; once the
 * count or the total size limit is reached, every later entry is left out (see
 * `CDT_EXPLANATION_LIMITS`). Normalized to `{}` rather than omitted, so a node
 * never explained and one whose explanations were all dropped stringify identically.
 */
export function toStoredCdtExplanations(explanations: CdtExplanations | undefined): Record<string, CdtExplanation> {
    const source: Record<string, unknown> = explanations ?? {};
    const stored: [string, CdtExplanation][] = [];
    // Compact JSON of what is kept: the braces, then each `"key":{...}` and a comma between.
    let storedBytes = 2;

    for (const key of Object.keys(source).sort(compareByCodePoint)) {
        const entry = toStorableEntry(key, source[key]);
        if (!entry) continue;

        const entryBytes = utf8Length(JSON.stringify({ [key]: entry })) - 2 + (stored.length > 0 ? 1 : 0);
        if (
            stored.length === CDT_EXPLANATION_LIMITS.maxEntries ||
            storedBytes + entryBytes > CDT_EXPLANATION_LIMITS.maxTotalBytes
        ) {
            break;
        }
        stored.push([key, entry]);
        storedBytes += entryBytes;
    }

    return Object.fromEntries(stored);
}

function toStorableEntry(key: string, value: unknown): CdtExplanation | null {
    if (!isStorableText(key, CDT_EXPLANATION_LIMITS.maxStepKeyLength)) return null;

    const explanation = toExplanation(value);
    if (!explanation) return null;

    const { text, fingerprint, generatedBy } = explanation;
    const isStorable =
        isStorableText(text, CDT_EXPLANATION_LIMITS.maxTextLength) &&
        isStorableText(generatedBy, CDT_EXPLANATION_LIMITS.maxGeneratedByLength) &&
        isStorableText(fingerprint, CDT_EXPLANATION_LIMITS.maxFingerprintLength);
    return isStorable ? { text, fingerprint, generatedBy } : null;
}

/** Non-empty, at most `maxLength` characters as the backend counts them (code points), nothing it refuses. */
function isStorableText(value: string, maxLength: number): boolean {
    if (value.length === 0 || UNSTORABLE_CHARACTER.test(value)) return false;
    // UTF-16 units never undercount code points, so the exact count is needed only past the limit.
    return value.length <= maxLength || Array.from(value).length <= maxLength;
}

/** The backend's order: Python compares strings by code point, not by UTF-16 unit. */
function compareByCodePoint(left: string, right: string): number {
    const rightCharacters = right[Symbol.iterator]();
    for (const leftCharacter of left) {
        const next = rightCharacters.next();
        if (next.done) return 1;
        const difference = leftCharacter.codePointAt(0)! - next.value.codePointAt(0)!;
        if (difference !== 0) return difference;
    }
    return rightCharacters.next().done ? 0 : -1;
}

function utf8Length(value: string): number {
    return UTF8.encode(value).length;
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
