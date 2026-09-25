import { PersistenceEntryLookup } from '../../../features/persistent-data/models/persistence-table.model';
import { PersistenceEntry, PersistenceMode, PersistenceReadEntry } from '../models/persistence-node.model';

// Mirrors crew's key-template parsing: placeholders match this regex, and a key with braces left over
// once they are removed is malformed. Keep both identical to crew so the panel flags what crew rejects.
const PLACEHOLDER = /\{([^{}]+)\}/g;
// Key placeholders and write values are flow state paths: `variables` plus at least one segment.
export const STATE_PATH = /^variables(\.\w|\[\d)/;

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

export function keyTemplateHint(template: string): string | null {
    if (isMalformedKey(template)) return 'Empty or unbalanced placeholder. Use e.g. {variables.user.id}';
    const invalid = nonStatePathPlaceholders(template);
    if (invalid.length === 0) return null;
    return `Not a state path: ${invalid.map((placeholder) => `{${placeholder}}`).join(', ')}. Use e.g. {variables.user.id}`;
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

export function reshapeEntriesForMode(entries: PersistenceEntry[], mode: PersistenceMode): PersistenceEntry[] {
    return entries.map(({ key }) => normalizeEntry({ key }, mode));
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
