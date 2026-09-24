import { PersistenceEntryLookup } from '../../../features/persistent-data/models/persistence-table.model';
import { PersistenceEntry, PersistenceMode } from '../models/persistence-node.model';

// Must stay identical to crew's key-template regex, so the panel flags exactly what crew rejects.
const PLACEHOLDER = /\{([^{}]+)\}/g;

export interface ExistenceBadge {
    kind: 'recorded' | 'missing' | 'dynamic' | 'unknown';
    label: string;
    tooltip: string | null;
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

export function reshapeEntriesForMode(entries: PersistenceEntry[], mode: PersistenceMode): PersistenceEntry[] {
    return entries.map(({ key }) => {
        if (mode === 'read') return { alias: '', key };
        if (mode === 'write') return { key, value: '' };
        return { key };
    });
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
