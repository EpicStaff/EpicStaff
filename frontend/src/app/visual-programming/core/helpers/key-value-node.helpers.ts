import { ActionCode, NodeType } from '@shared/models';

import { KeyValueEntryLookup } from '../../../features/key-value-tables/models/key-value-table.model';
import { KeyValueEntry, KeyValueMode, KeyValueNodeData } from '../models/key-value-node.model';
import { KeyValueNodeModel, NodeModel } from '../models/node.model';
import { isPathUnder } from './variable-path.util';

// Mirrors crew's key-template parsing: placeholders match this regex, and a key with braces left over
// once they are removed is malformed. Keep both identical to crew so the panel flags what crew rejects.
// Global, so .replace() replaces every placeholder. Only matchAll() and .replace() use it, and neither
// leaves a lastIndex behind, so it carries no state between calls.
const PLACEHOLDER = /\{([^{}]+)\}/g;
// Mirrors KEY_PATTERN in tables/constants/key_value_constants.py and crew key_value_node.py.
// A key, with each placeholder counted as one `_`. No `g` flag: .test() on it must not keep a lastIndex.
export const KEY_VALUE_KEY_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/;
// Mirrors MAX_KEY_LENGTH in tables/constants/key_value_constants.py.
export const KEY_VALUE_KEY_MAX_LENGTH = 512;
// Mirrors MAX_KEYS_PER_REQUEST in tables/constants/key_value_constants.py.
export const KEY_VALUE_MAX_KEYS = 500;
// Key placeholders, read targets and write sources (before any `|default`) are flow state paths.
// Mirrors crew and Django: `variables.` then ASCII word names or `[index]`, and no name may start
// with `_`. Flow variables are a dict in crew, so `variables[0]` can never resolve. An index is
// written canonically, without leading zeros: `[0]`, `[10]`, never `[01]`.
export const STATE_PATH = /^variables\.\w+(?:\.\w+|\[(?:0|[1-9]\d*)\])*$/;
const PRIVATE_NAME = /\._/;
// Keep in sync with DOTDICT_METHOD_NAMES in tables/validators/key_value_entries_validator.py.
// Crew's DotDict attribute access finds these methods before any stored name, so a path through
// one never resolves: crew rejects it in read targets, write sources and key placeholders alike.
const RESERVED_NAMES: ReadonlySet<string> = new Set([
    'add_property',
    'add_setter',
    'clear',
    'copy',
    'deep_dump',
    'fromkeys',
    'get',
    'items',
    'keys',
    'model_dump',
    'pop',
    'popitem',
    'setdefault',
    'update',
    'values',
]);
// Loosely rooted, so a path that only misspells its names gets the naming hint.
const ROOTED_PATH = /^variables\.\w/;
/** The key input's placeholder, which shows while the key is empty. */
export const KEY_PLACEHOLDER_HINT = 'Write placeholders as {variables.user.id}';
const KEY_BRACES_HINT = 'Close each { with } around a state path, like {variables.user.id}';
const KEY_CHARACTERS_HINT = 'Use letters, digits and _ outside {placeholders}, not starting with a digit';
const VALUE_PATH_HINT = 'Use a state path like variables.user.name';
const NAME_CHARACTERS_HINT = 'Use letters, digits and _ in variable names, like variables.user_name';
const PRIVATE_NAME_HINT = "Variable names can't start with _";
const READ_DEFAULT_HINT = 'Leave out the |default: a missing key reads None';
// A bare path such as `user.id` or `items[0]`, which only lacks the `variables.` root.
const ROOTLESS_PATH = /^[A-Za-z]\w*(?:\.[A-Za-z0-9]\w*|\[(?:0|[1-9]\d*)\])*$/;

// Mirrors MODE_PERMISSIONS in tables/services/key_value_table_service.py: what configuring a node
// in each mode needs on Key-Value Tables. The server is the authority; the panel only offers what it allows.
// Delete needs View too: its session messages carry the values it deleted.
export const KEY_VALUE_MODE_ACTIONS: Record<KeyValueMode, ActionCode[]> = {
    read: [ActionCode.Read],
    write: [ActionCode.Create, ActionCode.Update],
    delete: [ActionCode.Read, ActionCode.Delete],
};

/** Whether the user may configure a node in a mode: every action it needs, not any one of them. */
export function canConfigureMode(mode: KeyValueMode, can: (action: ActionCode) => boolean): boolean {
    return KEY_VALUE_MODE_ACTIONS[mode].every(can);
}

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

const EXISTS_HINT: Record<KeyValueMode, string> = {
    read: 'Exists',
    write: 'Exists — will overwrite',
    delete: 'Exists',
};

const MISSING_HINT: Record<KeyValueMode, string> = {
    read: 'New key — reads None',
    write: 'New key',
    delete: 'Not recorded — no-op',
};

export function extractPlaceholders(template: string): string[] {
    return Array.from(template.matchAll(PLACEHOLDER), (match) => match[1]);
}

/** The first name in a path that is a reserved DotDict method name, or null. */
function reservedName(path: string): string | null {
    return path.match(/\w+/g)?.find((name) => RESERVED_NAMES.has(name)) ?? null;
}

/** Crew tolerates whitespace around a path, so the panel does too. */
export function isStatePath(text: string): boolean {
    const path = text.trim();
    return STATE_PATH.test(path) && !PRIVATE_NAME.test(path) && reservedName(path) === null;
}

/** A write value: a state path, optionally followed by `|default`. */
export function isWriteSource(text: string): boolean {
    return isStatePath(text.split('|')[0]);
}

/** Why a path that starts like a state path, or is one without the `variables.` root, is not one, or null. */
function namingHint(path: string): string | null {
    const trimmed = path.trim();
    const reserved = reservedName(trimmed);
    if (reserved !== null && (STATE_PATH.test(trimmed) || isRootlessPath(trimmed))) {
        return `Use a different name — '${reserved}' is reserved`;
    }
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

/** A path that only lacks the `variables.` root, not one that tries a root such as `Variables.`. */
function isRootlessPath(path: string): boolean {
    return !path.toLowerCase().startsWith('variables') && ROOTLESS_PATH.test(path);
}

/** The state path the user most likely meant, or null when it can't be guessed or could never resolve. */
export function suggestStatePath(text: string): string | null {
    const path = text.trim();
    if (!isRootlessPath(path) || reservedName(path) !== null) return null;
    return `variables.${path}`;
}

/** A template starting with a placeholder passes here; crew checks the key it resolves to at run time. */
export function keyTemplateHint(template: string): string | null {
    if (isMalformedKey(template)) return KEY_BRACES_HINT;
    const invalid = Array.from(new Set(nonStatePathPlaceholders(template)));
    if (invalid.length > 0) {
        const fixes = invalid.map(suggestStatePath);
        if (fixes.every((fix): fix is string => fix !== null))
            return `Use ${fixes.map((fix) => `{${fix}}`).join(', ')}`;
        return invalid.map(namingHint).find((hint) => hint !== null) ?? KEY_BRACES_HINT;
    }
    // A blank key is keyError's 'required', which has no hint: an empty row must stay quiet.
    if (template.trim() === '') return null;
    return KEY_VALUE_KEY_PATTERN.test(template.replace(PLACEHOLDER, '_')) ? null : KEY_CHARACTERS_HINT;
}

/** Read targets are plain state paths; write sources may add `|default`. */
export function valuePathHint(value: string, mode: KeyValueMode): string | null {
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
    if (key.length > KEY_VALUE_KEY_MAX_LENGTH) return 'maxlength';
    return keyTemplateHint(key) === null ? null : 'keyTemplate';
}

/** What is wrong with a read target or a write source, or null. Read targets take no `|default`. */
export function valueError(value: string, mode: KeyValueMode): 'required' | 'pattern' | null {
    if (value === '') return 'required';
    return (mode === 'read' ? isStatePath(value) : isWriteSource(value)) ? null : 'pattern';
}

/** A write source's state path: what comes before any `|default`, trimmed. */
export function writeSourcePath(value: string): string {
    return value.split('|')[0].trim();
}

/** The texts that occur more than once. */
function repeated(texts: string[]): Set<string> {
    const seen = new Set<string>();
    const duplicates = new Set<string>();
    texts.forEach((text) => (seen.has(text) ? duplicates : seen).add(text));
    return duplicates;
}

/**
 * Keys written by more than one write row: the later row would overwrite the earlier one. A key
 * keyError rejects is left to it, so it never counts here; one it accepts has no spaces around it,
 * so keys compare as typed. Read and delete allow repeated keys, and write rows may share a source
 * variable.
 */
export function duplicateWriteKeys(keys: string[]): Set<string> {
    return repeated(keys.filter((key) => keyError(key) === null));
}

/** A read target valueError accepts, trimmed; null for one it rejects, which is left to it. */
export function validReadTarget(value: string): string | null {
    return valueError(value, 'read') === null ? value.trim() : null;
}

/**
 * Whether one of two trimmed state paths lies inside the other, compared name by name, so
 * `variables.user` holds `variables.user.name` and `variables.user[0]` but not `variables.username`.
 */
export function isNestedPath(path: string, otherPath: string): boolean {
    return isPathUnder(path, otherPath) || isPathUnder(otherPath, path);
}

/**
 * How a read target clashes with the read targets of all rows, its own included: another row fills
 * the same variable ('duplicate'), or one inside or around it ('overlap'), so the later row would
 * overwrite the earlier one. Null when it doesn't, or when valueError rejects it. Read rows may share a key.
 * Compares one target with the others, so a check of every row stays quadratic.
 */
export function readTargetConflict(value: string, values: string[]): 'duplicate' | 'overlap' | null {
    const target = validReadTarget(value);
    if (target === null) return null;
    const targets = values.map(validReadTarget).filter((other): other is string => other !== null);
    if (targets.filter((other) => other === target).length > 1) return 'duplicate';
    return targets.some((other) => isNestedPath(target, other)) ? 'overlap' : null;
}

/** For a node whose panel may be closed: the flow save refuses one that breaks the entry rules. */
export function hasValidKeyValueEntries({ mode, entries }: KeyValueNodeData): boolean {
    const keys = entries.map((entry) => entry.key);
    const values = entries.map((entry) => ('value' in entry ? entry.value : ''));
    const duplicateKeys = mode === 'write' ? duplicateWriteKeys(keys) : new Set<string>();
    return (
        entries.filter((entry) => !isEmptyEntry(entry)).length <= KEY_VALUE_MAX_KEYS &&
        entries.every(
            (entry, index) =>
                keyError(entry.key) === null &&
                !duplicateKeys.has(entry.key) &&
                (mode !== 'read' || readTargetConflict(values[index], values) === null) &&
                (mode === 'delete' || valueError(values[index], mode) === null)
        )
    );
}

/** One message per key-value node the flow save must refuse. */
export function invalidKeyValueNodeMessages(nodes: NodeModel[]): string[] {
    return nodes
        .filter((node): node is KeyValueNodeModel => node.type === NodeType.KEY_VALUE)
        .filter((node) => !hasValidKeyValueEntries(node.data))
        .map((node) => `"${node.node_name}" has invalid keys or variable paths`);
}

/**
 * Builds the canonical entry for a mode, with a fixed key order. Save diffs compare entries with
 * JSON.stringify, and jsonb hands object keys back sorted, so the loader and the panel must both
 * go through here or an unchanged node reads as changed.
 */
export function normalizeEntry(entry: EntryFields, mode: KeyValueMode): KeyValueEntry {
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
export function existenceHint(mode: KeyValueMode, lookup: KeyValueEntryLookup | undefined): string | null {
    if (!lookup) return null;
    return lookup.exists ? EXISTS_HINT[mode] : MISSING_HINT[mode];
}
