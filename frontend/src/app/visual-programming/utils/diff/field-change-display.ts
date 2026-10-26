import { UnionNodeDiffState } from './build-union-flow-model';
import { fieldFormat, FieldName } from './field-display';
import { isSameValue, stableStringify } from './normalize';
import { FieldChange, FieldChangeStatus } from './types';

// How a node panel shows one field change: which change a field has, and the current value split into the
// parts a restore keeps and the parts it replaces. Display only; the diff engine never reads this.

/** A run of a value's text; `struck` = a restore replaces it. */
export interface DisplaySegment {
    text: string;
    struck: boolean;
}

/** What a restore does to one key of a map field, like `input_map`. */
export interface MapKeyChange {
    key: string;
    /** `added` = the key is in the version only, `deleted` = on the canvas only. */
    status: FieldChangeStatus;
    /** `null` when the canvas lacks the key. */
    current: unknown;
    /** `null` when the version lacks the key. */
    version: unknown;
}

const EMPTY_TEXT = 'empty';
const LIST_SEPARATOR = ', ';
/** How much unchanged text (in graphemes) a tooltip keeps on each side of the part a restore replaces. */
const TEXT_CONTEXT_LENGTH = 40;
/** A struck part longer than this (in graphemes) keeps only its ends, so a rewritten long text stays readable. */
const STRUCK_PART_MAX_LENGTH = 120;
/** How much of each end of a capped struck part is kept. */
const STRUCK_PART_KEPT_END = 50;
const CUT_MARK = '…';

/**
 * Field marks show only on a node a restore changes. An added or removed node is marked as a whole (the panel
 * banner), and off the Changes tab there is no diff.
 */
export function showsFieldMarks(diff: Pick<UnionNodeDiffState, 'status'> | null): boolean {
    return diff?.status === 'changed';
}

/**
 * What a restore does to each key of a map field (like `input_map`, which the diff compares as one value), for
 * per-row marks; `null` when the node shows no field marks or the field is unchanged.
 */
export function mapFieldRowChanges(diff: UnionNodeDiffState | null, field: FieldName): MapKeyChange[] | null {
    if (!showsFieldMarks(diff)) return null;
    const change = fieldChangeFor(diff, field);
    return change ? mapKeyChanges(change.current, change.version) : null;
}

/** The change of `field`, or of one of its items when `path` is given; `null` when it has none. */
export function fieldChangeFor(
    diff: Pick<UnionNodeDiffState, 'fields'> | null,
    field: FieldName,
    path: string = field
): FieldChange | null {
    return diff?.fields.find((change) => change.field === field && change.path === path) ?? null;
}

/**
 * The current value of a field as the tooltip shows it, the parts a restore replaces struck:
 * - `defaultValue` (when given) stands in for a side that is `null` or `undefined` (no value of its own), as the
 *   field shows it in that case (e.g. the default timeout). An empty text or list is a value and is not replaced;
 * - a field with a display formatter (`FIELD_DISPLAY`) shows the formatted text, struck as a whole when the
 *   formatted sides differ;
 * - any other value: `struckSegments`.
 * `field` is `null` for a change the caller worked out (e.g. one key of a map), which has no formatter.
 */
export function fieldValueSegments(
    field: FieldName | null,
    current: unknown,
    version: unknown,
    defaultValue?: unknown
): DisplaySegment[] {
    const shown = (value: unknown): unknown => (value == null && defaultValue !== undefined ? defaultValue : value);
    const format = field ? fieldFormat(field) : undefined;
    if (!format) return struckSegments(shown(current), shown(version));
    const textOf = (value: unknown): string => {
        const shown = value == null && defaultValue !== undefined ? defaultValue : value;
        return isEmpty(shown) ? EMPTY_TEXT : format(shown);
    };
    const currentText = textOf(current);
    return [{ text: currentText, struck: currentText !== textOf(version) }];
}

/**
 * The current value as text segments, the parts a restore replaces struck:
 * - text: the common start and end with the version value are kept, the middle is struck. Compared by
 *   grapheme (what a reader sees as one character), so an emoji or an accent is never split. The kept text is
 *   cut to `TEXT_CONTEXT_LENGTH` graphemes on each side of the struck part, with "…" where it was cut. A struck
 *   part longer than `STRUCK_PART_MAX_LENGTH` keeps only its first and last `STRUCK_PART_KEPT_END` graphemes,
 *   with an unstruck "…" between them;
 * - a list: the items the version does not have are struck; a repeated item is kept only as many times as the
 *   version has it. A long struck item is capped like a struck part of text, a long kept item cut to
 *   `TEXT_CONTEXT_LENGTH` graphemes;
 * - a number, a flag, or a value of another type than the version's: struck whole;
 * - a structured value: compared as its JSON text, cut the same way;
 * - `null`, `''`, an empty list or map: one struck "empty".
 */
function struckSegments(current: unknown, version: unknown): DisplaySegment[] {
    if (isEmpty(current)) return [{ text: EMPTY_TEXT, struck: true }];
    if (Array.isArray(current)) return listSegments(current, Array.isArray(version) ? version : []);
    if (typeof current === 'string') {
        return typeof version === 'string' ? textSegments(current, version) : [{ text: current, struck: true }];
    }
    if (typeof current === 'object') {
        const versionText = version !== null && typeof version === 'object' ? stableStringify(version) : '';
        return textSegments(stableStringify(current), versionText);
    }
    return [{ text: scalarText(current), struck: true }];
}

/**
 * The keys whose value a restore changes, adds or removes, version keys first in their order, then the keys
 * only the canvas has. A value that is not a map counts as an empty map.
 */
function mapKeyChanges(current: unknown, version: unknown): MapKeyChange[] {
    const currentMap = asMap(current);
    const versionMap = asMap(version);
    const changes: MapKeyChange[] = [];
    for (const [key, versionValue] of Object.entries(versionMap)) {
        if (!Object.hasOwn(currentMap, key)) {
            changes.push({ key, status: 'added', current: null, version: versionValue });
        } else if (!isSameValue(currentMap[key], versionValue)) {
            changes.push({ key, status: 'changed', current: currentMap[key], version: versionValue });
        }
    }
    for (const [key, currentValue] of Object.entries(currentMap)) {
        if (!Object.hasOwn(versionMap, key)) {
            changes.push({ key, status: 'deleted', current: currentValue, version: null });
        }
    }
    return changes;
}

function textSegments(currentText: string, versionText: string): DisplaySegment[] {
    const current = graphemes(currentText);
    const version = graphemes(versionText);
    let prefix = 0;
    while (prefix < current.length && prefix < version.length && current[prefix] === version[prefix]) prefix++;
    let suffix = 0;
    while (
        suffix < current.length - prefix &&
        suffix < version.length - prefix &&
        current[current.length - 1 - suffix] === version[version.length - 1 - suffix]
    ) {
        suffix++;
    }
    const before = current.slice(0, prefix);
    const after = current.slice(current.length - suffix);
    const segments: DisplaySegment[] = [
        { text: lastContext(before), struck: false },
        ...struckPart(current.slice(prefix, current.length - suffix)),
        { text: firstContext(after), struck: false },
    ];
    return segments.filter((segment) => segment.text !== '');
}

/** The part a restore replaces, struck; only its two ends when it is long, the cut mark between them not struck. */
function struckPart(replaced: readonly string[]): DisplaySegment[] {
    if (replaced.length <= STRUCK_PART_MAX_LENGTH) return [{ text: replaced.join(''), struck: true }];
    return [
        { text: replaced.slice(0, STRUCK_PART_KEPT_END).join(''), struck: true },
        { text: CUT_MARK, struck: false },
        { text: replaced.slice(-STRUCK_PART_KEPT_END).join(''), struck: true },
    ];
}

/** The kept text before the struck part: its end, "…" in front when cut. */
function lastContext(kept: readonly string[]): string {
    return kept.length > TEXT_CONTEXT_LENGTH ? CUT_MARK + kept.slice(-TEXT_CONTEXT_LENGTH).join('') : kept.join('');
}

/** The kept text after the struck part: its start, "…" after it when cut. */
function firstContext(kept: readonly string[]): string {
    return kept.length > TEXT_CONTEXT_LENGTH ? kept.slice(0, TEXT_CONTEXT_LENGTH).join('') + CUT_MARK : kept.join('');
}

/** The user-perceived characters (graphemes): an emoji with its modifiers, a letter with its accents. */
function graphemes(text: string): string[] {
    return Array.from(new Intl.Segmenter(undefined, { granularity: 'grapheme' }).segment(text), (part) => part.segment);
}

/** Each current item uses up one equal version item; one with no equal item left is struck. */
function listSegments(current: readonly unknown[], version: readonly unknown[]): DisplaySegment[] {
    const unmatched = [...version];
    return current.flatMap((item, index) => {
        const match = unmatched.findIndex((candidate) => isSameValue(candidate, item));
        if (match !== -1) unmatched.splice(match, 1);
        const text = graphemes(itemText(item));
        const parts = match === -1 ? struckPart(text) : [{ text: firstContext(text), struck: false }];
        return index === 0 ? parts : [{ text: LIST_SEPARATOR, struck: false }, ...parts];
    });
}

function itemText(item: unknown): string {
    if (typeof item === 'string') return item;
    return item !== null && typeof item === 'object' ? stableStringify(item) : scalarText(item);
}

function scalarText(value: unknown): string {
    if (typeof value === 'boolean') return value ? 'on' : 'off';
    return String(value);
}

function isEmpty(value: unknown): boolean {
    if (value === null || value === undefined || value === '') return true;
    if (Array.isArray(value)) return value.length === 0;
    return typeof value === 'object' && Object.keys(value).length === 0;
}

function asMap(value: unknown): Record<string, unknown> {
    return value !== null && typeof value === 'object' && !Array.isArray(value)
        ? (value as Record<string, unknown>)
        : {};
}
