import { PersistenceEntryLookup } from '../../../features/persistent-data/models/persistence-table.model';
import { PersistenceEntry, PersistenceMode, PersistenceReadEntry } from '../models/persistence-node.model';

// Mirrors crew's key-template parsing: placeholders match this regex, and a key with braces left over
// once they are removed is malformed. Keep both identical to crew so the panel flags what crew rejects.
const PLACEHOLDER = /\{([^{}]+)\}/g;
// Key placeholders and write values are flow state paths: `variables` plus at least one segment.
export const STATE_PATH = /^variables(\.\w|\[\d)/;
const KEY_PLACEHOLDER_HINT = 'Write placeholders as {variables.user.id}';
const WRITE_VALUE_HINT = 'Use a state path like variables.user.name';
// A bare path such as `user.id` or `items[0]`, which only lacks the `variables.` root.
const ROOTLESS_PATH = /^[A-Za-z_]\w*(\.\w+|\[\d+\])*$/;

/** A write value starts as this so the user only types the rest of the path. */
export const WRITE_VALUE_PREFILL = 'variables.';

export interface ExistenceBadge {
    kind: 'recorded' | 'missing' | 'dynamic' | 'unknown';
    label: string;
    tooltip: string | null;
}

export interface LookupRequest {
    table: number | null;
    staticKeys: string[];
}

interface EntryFields {
    key: string;
    alias?: string;
    value?: string;
    default?: unknown;
}

/** A panel row as typed; `default` is still the raw text. */
interface EntryText {
    key?: string | null;
    alias?: string | null;
    value?: string | null;
    default?: string | null;
}

const RECORDED_LABEL: Record<PersistenceMode, string> = {
    read: 'recorded',
    write: 'exists — will overwrite',
    delete: 'recorded',
};

const MISSING_LABEL: Record<PersistenceMode, string> = {
    read: 'not recorded — returns default',
    write: 'new key',
    delete: 'not recorded — no-op',
};

export function extractPlaceholders(template: string): string[] {
    return Array.from(template.matchAll(PLACEHOLDER), (match) => match[1]);
}

/** Crew tolerates whitespace around a path, so the panel does too. */
export function isStatePath(text: string): boolean {
    return STATE_PATH.test(text.trim());
}

/** An empty `{}` or an unbalanced brace. */
export function isMalformedKey(template: string): boolean {
    return /[{}]/.test(template.replace(PLACEHOLDER, ''));
}

export function isStaticKey(template: string): boolean {
    return !isMalformedKey(template) && extractPlaceholders(template).length === 0;
}

export function nonStatePathPlaceholders(template: string): string[] {
    return extractPlaceholders(template).filter((placeholder) => !isStatePath(placeholder));
}

/** The state path the user most likely meant, or null when it can't be guessed. */
export function suggestStatePath(text: string): string | null {
    const path = text.trim();
    if (path.toLowerCase().startsWith('variables') || !ROOTLESS_PATH.test(path)) return null;
    return `variables.${path}`;
}

export function keyTemplateHint(template: string): string | null {
    if (isMalformedKey(template)) return KEY_PLACEHOLDER_HINT;
    const invalid = Array.from(new Set(nonStatePathPlaceholders(template)));
    if (invalid.length === 0) return null;
    const fixes = invalid.map(suggestStatePath);
    if (!fixes.every((fix): fix is string => fix !== null)) return KEY_PLACEHOLDER_HINT;
    return `Use ${fixes.map((fix) => `{${fix}}`).join(', ')}`;
}

export function writeValueHint(value: string): string | null {
    if (value.trim() === '' || isStatePath(value)) return null;
    const fix = suggestStatePath(value);
    return fix === null ? WRITE_VALUE_HINT : `Use ${fix}`;
}

/**
 * Builds the canonical entry for a mode, with a fixed key order. Save diffs compare entries with
 * JSON.stringify, and jsonb hands object keys back sorted, so the loader and the panel must both
 * go through here or an unchanged node reads as changed.
 */
export function normalizeEntry(entry: EntryFields, mode: PersistenceMode): PersistenceEntry {
    if (mode === 'read') {
        const readEntry: PersistenceReadEntry = { alias: entry.alias ?? '', key: entry.key };
        if (entry.default !== undefined) readEntry.default = entry.default;
        return readEntry;
    }
    if (mode === 'write') return { key: entry.key, value: entry.value ?? '' };
    return { key: entry.key };
}

/**
 * A panel row with nothing typed, such as one just added with "Add key". A write value still at
 * its prefill counts as nothing typed. The panel neither validates nor saves such a row.
 */
export function isEmptyEntry(row: EntryText): boolean {
    const text = (field: string | null | undefined): string => (field ?? '').trim();
    return (
        [row.key, row.alias, row.default].every((field) => text(field) === '') &&
        ['', WRITE_VALUE_PREFILL].includes(text(row.value))
    );
}

export function reshapeEntriesForMode(entries: PersistenceEntry[], mode: PersistenceMode): PersistenceEntry[] {
    return entries.map(({ key }) => normalizeEntry({ key, value: WRITE_VALUE_PREFILL }, mode));
}

export function isSameLookupRequest(previous: LookupRequest, current: LookupRequest): boolean {
    return (
        previous.table === current.table &&
        previous.staticKeys.length === current.staticKeys.length &&
        previous.staticKeys.every((key, index) => key === current.staticKeys[index])
    );
}

export function parseDefaultValue(text: string): unknown {
    if (text.trim() === '') return undefined;
    try {
        return JSON.parse(text);
    } catch {
        return text;
    }
}

export function existenceBadge(
    mode: PersistenceMode,
    template: string,
    lookup: PersistenceEntryLookup | undefined
): ExistenceBadge {
    if (isMalformedKey(template)) {
        return { kind: 'unknown', label: '', tooltip: null };
    }
    if (!isStaticKey(template)) {
        return { kind: 'dynamic', label: 'resolved at run time', tooltip: null };
    }
    if (!lookup) {
        return { kind: 'unknown', label: '', tooltip: null };
    }
    return lookup.exists
        ? { kind: 'recorded', label: RECORDED_LABEL[mode], tooltip: lookup.value_preview }
        : { kind: 'missing', label: MISSING_LABEL[mode], tooltip: null };
}
