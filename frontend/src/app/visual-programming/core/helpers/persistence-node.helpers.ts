import { NodeType } from '@shared/models';

import { PersistenceEntryLookup } from '../../../features/persistent-data/models/persistence-table.model';
import { NodeModel, PersistenceNodeModel } from '../models/node.model';
import { PersistenceEntry, PersistenceMode, PersistenceNodeData } from '../models/persistence-node.model';

// Mirrors crew's key-template parsing: placeholders match this regex, and a key with braces left over
// once they are removed is malformed. Keep both identical to crew so the panel flags what crew rejects.
const PLACEHOLDER = /\{([^{}]+)\}/g;
// Mirrors MAX_KEY_LENGTH in tables/constants/persistence_constants.py.
export const PERSISTENCE_KEY_MAX_LENGTH = 512;
// Key placeholders, read targets and write sources (before any `|default`) are flow state paths.
// Mirrors crew and Django: `variables.` then ASCII word names or `[index]`, and no name may start
// with `_`. Flow variables are a dict in crew, so `variables[0]` can never resolve.
export const STATE_PATH = /^variables\.\w+(?:\.\w+|\[\d+\])*$/;
const PRIVATE_NAME = /\._/;
// Loosely rooted, so a path that only misspells its names gets the naming hint.
const ROOTED_PATH = /^variables\.\w/;
const KEY_PLACEHOLDER_HINT = 'Write placeholders as {variables.user.id}';
const VALUE_PATH_HINT = 'Use a state path like variables.user.name';
const NAME_CHARACTERS_HINT = 'Use letters, digits and _ in variable names, like variables.user_name';
const PRIVATE_NAME_HINT = "Variable names can't start with _";
const READ_DEFAULT_HINT = 'Leave out the |default: a missing key reads None';
// A bare path such as `user.id` or `items[0]`, which only lacks the `variables.` root.
const ROOTLESS_PATH = /^[A-Za-z]\w*(?:\.[A-Za-z0-9]\w*|\[\d+\])*$/;

/** A read or write value starts as this so the user only types the rest of the path. */
export const VALUE_PREFILL = 'variables.';

export interface LookupRequest {
    table: number | null;
    staticKeys: string[];
}

interface EntryFields {
    key: string;
    value?: string;
}

/** A panel row as typed. */
interface EntryText {
    key?: string | null;
    value?: string | null;
}

const EXISTS_HINT: Record<PersistenceMode, string> = {
    read: 'Exists',
    write: 'Exists — will overwrite',
    delete: 'Exists',
};

const MISSING_HINT: Record<PersistenceMode, string> = {
    read: 'New key — reads None',
    write: 'New key',
    delete: 'Not recorded — no-op',
};

export function extractPlaceholders(template: string): string[] {
    return Array.from(template.matchAll(PLACEHOLDER), (match) => match[1]);
}

/** Crew tolerates whitespace around a path, so the panel does too. */
export function isStatePath(text: string): boolean {
    const path = text.trim();
    return STATE_PATH.test(path) && !PRIVATE_NAME.test(path);
}

/** A write value: a state path, optionally followed by `|default`. */
export function isWriteSource(text: string): boolean {
    return isStatePath(text.split('|')[0]);
}

/** Why a path that starts like a state path is not one, or null. */
function namingHint(path: string): string | null {
    const trimmed = path.trim();
    if (STATE_PATH.test(trimmed)) return PRIVATE_NAME.test(trimmed) ? PRIVATE_NAME_HINT : null;
    return ROOTED_PATH.test(trimmed) ? NAME_CHARACTERS_HINT : null;
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
    if (fixes.every((fix): fix is string => fix !== null)) return `Use ${fixes.map((fix) => `{${fix}}`).join(', ')}`;
    return invalid.map(namingHint).find((hint) => hint !== null) ?? KEY_PLACEHOLDER_HINT;
}

/** Read targets are plain state paths; write sources may add `|default`. */
export function valuePathHint(value: string, mode: PersistenceMode): string | null {
    const [path, ...defaultParts] = value.split('|');
    if (mode === 'read' && defaultParts.length > 0) return READ_DEFAULT_HINT;
    if (value.trim() === '' || isStatePath(path)) return null;
    const fix = suggestStatePath(path);
    if (fix !== null) return `Use ${[fix, ...defaultParts].join('|')}`;
    return namingHint(path) ?? VALUE_PATH_HINT;
}

// The entry rules below are the single source for both the panel's validators and the flow save.

/** What is wrong with a key, named like the Angular validator errors, or null. */
export function keyError(key: string): 'required' | 'maxlength' | 'keyTemplate' | null {
    if (key.trim() === '') return 'required';
    if (key.length > PERSISTENCE_KEY_MAX_LENGTH) return 'maxlength';
    return keyTemplateHint(key) === null ? null : 'keyTemplate';
}

/** What is wrong with a read target or a write source, or null. Read targets take no `|default`. */
export function valueError(value: string, mode: PersistenceMode): 'required' | 'pattern' | null {
    if (value === '') return 'required';
    return (mode === 'read' ? isStatePath(value) : isWriteSource(value)) ? null : 'pattern';
}

/** A write source's state path: what comes before any `|default`, trimmed. */
export function writeSourcePath(value: string): string {
    return value.split('|')[0].trim();
}

/**
 * Keys written by more than one write row, trimmed: the later row would overwrite the earlier one.
 * A key keyError rejects is left to it, so it never counts here. Read and delete allow repeats, and
 * write rows may share a source variable.
 */
export function duplicateWriteKeys(keys: string[]): Set<string> {
    const seen = new Set<string>();
    const duplicates = new Set<string>();
    keys.filter((key) => keyError(key) === null)
        .map((key) => key.trim())
        .forEach((key) => (seen.has(key) ? duplicates : seen).add(key));
    return duplicates;
}

/** For a node whose panel may be closed: the flow save refuses one that breaks the entry rules. */
export function hasValidPersistenceEntries({ mode, entries }: PersistenceNodeData): boolean {
    const keys = entries.map((entry) => entry.key);
    const values = entries.map((entry) => ('value' in entry ? entry.value : ''));
    const duplicateKeys = mode === 'write' ? duplicateWriteKeys(keys) : new Set<string>();
    return entries.every(
        (entry, index) =>
            keyError(entry.key) === null &&
            !duplicateKeys.has(entry.key.trim()) &&
            (mode === 'delete' || valueError(values[index], mode) === null)
    );
}

/** One message per persistence node the flow save must refuse. */
export function invalidPersistenceNodeMessages(nodes: NodeModel[]): string[] {
    return nodes
        .filter((node): node is PersistenceNodeModel => node.type === NodeType.PERSISTENCE)
        .filter((node) => !hasValidPersistenceEntries(node.data))
        .map((node) => `"${node.node_name}" has invalid keys or variable paths`);
}

/**
 * Builds the canonical entry for a mode, with a fixed key order. Save diffs compare entries with
 * JSON.stringify, and jsonb hands object keys back sorted, so the loader and the panel must both
 * go through here or an unchanged node reads as changed.
 */
export function normalizeEntry(entry: EntryFields, mode: PersistenceMode): PersistenceEntry {
    if (mode === 'delete') return { key: entry.key };
    return { key: entry.key, value: entry.value ?? '' };
}

/**
 * A panel row with nothing typed, such as one just added with "Add key". A value still at its
 * prefill counts as nothing typed. The panel neither validates nor saves such a row.
 */
export function isEmptyEntry(row: EntryText): boolean {
    return (row.key ?? '').trim() === '' && ['', VALUE_PREFILL].includes((row.value ?? '').trim());
}

/**
 * For each key, how many keys before it are the same: 0 for the first. With the key, this tells
 * apart rows whose keys repeat, including rows with no key yet, which all share ''.
 */
export function keyOccurrences(keys: string[]): number[] {
    const seen = new Map<string, number>();
    return keys.map((key) => {
        const occurrence = seen.get(key) ?? 0;
        seen.set(key, occurrence + 1);
        return occurrence;
    });
}

export function isSameLookupRequest(previous: LookupRequest, current: LookupRequest): boolean {
    return (
        previous.table === current.table &&
        previous.staticKeys.length === current.staticKeys.length &&
        previous.staticKeys.every((key, index) => key === current.staticKeys[index])
    );
}

/** Whether a looked-up key is stored. Only static keys are looked up, so any other key gets null. */
export function existenceHint(mode: PersistenceMode, lookup: PersistenceEntryLookup | undefined): string | null {
    if (!lookup) return null;
    return lookup.exists ? EXISTS_HINT[mode] : MISSING_HINT[mode];
}
