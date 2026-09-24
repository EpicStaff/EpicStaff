import { PersistenceEntryLookup } from '../../../features/persistent-data/models/persistence-table.model';
import { PersistenceEntry, PersistenceMode, PersistenceReadEntry } from '../models/persistence-node.model';

// Must stay identical to crew's key-template regex, so the panel flags exactly what crew rejects.
const PLACEHOLDER = /\{([^{}]+)\}/g;

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

export function isStaticKey(template: string): boolean {
    return extractPlaceholders(template).length === 0;
}

export function missingPlaceholders(template: string, inputMapKeys: string[]): string[] {
    const known = new Set(inputMapKeys);
    return extractPlaceholders(template).filter((name) => !known.has(name));
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
