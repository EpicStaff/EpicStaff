import { UnionNodeDiffState } from './build-union-flow-model';
import { fieldFormat, FieldName } from './field-display';
import { isSameValue, stableStringify } from './normalize';
import { keyPrefixOf } from './semantic-projections';
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

/** A code field: shown in a code editor, so its change is shown as a code diff, not in a tooltip. */
export type CodeFieldName = Extract<FieldName, 'python_code.code' | 'pre_computation.code' | 'post_computation.code'>;

/** A JSON field shown in a JSON editor: its change is shown as a code diff of the JSON text, like code. */
export type JsonFieldName = Extract<FieldName, 'variables' | 'output_map' | 'output_schema'>;

/** A field whose items the diff pairs by a key of their own and compares field by field (`KEYED_COLLECTIONS`). */
export type KeyedCollectionName = Extract<FieldName, 'tasks' | 'condition_groups' | 'prompts'>;

/** What a restore does to one item of a keyed collection, e.g. the second task of an Agent node. */
export interface KeyedItemChange {
    /** The item's key as the diff writes it in a path: `2` for the second task, `yes` for the group named "yes". */
    key: string;
    /** `added` = the item is in the version only, `deleted` = on the canvas only. */
    status: FieldChangeStatus;
    /** For a changed item: the item fields a restore changes (`name`), in the diff's order; empty otherwise. */
    fields: string[];
    /**
     * A changed item: the canvas value of each field in `fields`, by field. An added item: `null`. A deleted item: the
     * whole item.
     */
    current: unknown;
    /** A changed item: the version value of each field in `fields`, by field. An added item: the whole item. */
    version: unknown;
}

/** Both sides of a changed code field as the code diff shows them. */
export interface CodeChange {
    current: string;
    version: string;
}

/**
 * What a restore does to the rows of a list field paired by a key of their own (Key-Value entries by key), which
 * the diff compares as one value.
 */
export interface ListRowChanges {
    /** One per version item, in its order: what a restore does to that row; `null` for a row it keeps. */
    rows: (MapKeyChange | null)[];
    /** The items only the canvas has (a restore removes them), in their canvas order. */
    removed: MapKeyChange[];
}

const EMPTY_TEXT = 'empty';
const LIST_SEPARATOR = ', ';
/** How much of the start of a long text (in graphemes) a tooltip always shows; also the cut of a long kept list item. */
const VALUE_START_LENGTH = 40;
/** How much unchanged text (in graphemes) a tooltip keeps right before and right after the part a restore replaces. */
const CHANGE_CONTEXT_LENGTH = 20;
/** A struck part longer than this (in graphemes) keeps only its ends, so a rewritten long text stays readable. */
const STRUCK_PART_MAX_LENGTH = 120;
/** How much of each end of a capped struck part is kept. */
const STRUCK_PART_KEPT_END = 50;
/** How many lines of the start of a long text a tooltip shows at most; also the cut of a kept list item. */
const VALUE_START_MAX_LINES = 3;
/**
 * How many lines of unchanged text a tooltip keeps right before and right after the struck part at most, counting the
 * line the struck part starts or ends on.
 */
const CHANGE_CONTEXT_MAX_LINES = 2;
/** A struck part with more lines than this keeps only its ends, so a rewritten text of many lines stays short. */
const STRUCK_PART_MAX_LINES = 6;
/** How many lines of each end of a capped struck part are kept. */
const STRUCK_PART_KEPT_END_LINES = 3;
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

/**
 * The change of a code field for the code diff; `null` when the node shows no field marks or the code is unchanged.
 * A side with no code shows as empty text.
 */
export function codeChangeFor(diff: UnionNodeDiffState | null, field: CodeFieldName): CodeChange | null {
    if (!showsFieldMarks(diff)) return null;
    const change = fieldChangeFor(diff, field);
    return change ? { current: codeText(change.current), version: codeText(change.version) } : null;
}

/**
 * Whether a restore changes any of `fields` or anything inside them (`pre_computation` covers
 * `pre_computation.code`), e.g. to flag a panel tab that shows them; `false` when the node shows no field marks.
 */
export function changesAnyFieldIn(diff: UnionNodeDiffState | null, fields: readonly FieldName[]): boolean {
    if (diff === null || !showsFieldMarks(diff)) return false;
    return diff.fields.some((change) =>
        fields.some((field) => change.field === field || change.field.startsWith(`${field}.`))
    );
}

/**
 * The change of a JSON field for the code diff, both sides as the JSON editor shows them (indented by 2); `null`
 * when the node shows no field marks or the field is unchanged.
 */
export function jsonChangeFor(diff: UnionNodeDiffState | null, field: JsonFieldName): CodeChange | null {
    if (!showsFieldMarks(diff)) return null;
    const change = fieldChangeFor(diff, field);
    return change ? { current: jsonText(change.current), version: jsonText(change.version) } : null;
}

/**
 * The change of a JSON field of one item of a keyed collection (e.g. `output_schema` of the second task) for the code
 * diff, both sides as the JSON editor shows them (indented by 2); `null` when the node shows no field marks, the item
 * is not on both sides (added or removed whole), or that field of it is unchanged.
 */
export function keyedItemJsonChangeFor(
    diff: UnionNodeDiffState | null,
    collection: KeyedCollectionName,
    key: string,
    field: string
): CodeChange | null {
    const item = keyedItemChanges(diff, collection)?.find((candidate) => candidate.key === key);
    if (item?.status !== 'changed' || !item.fields.includes(field)) return null;
    return { current: jsonText(asMap(item.current)[field]), version: jsonText(asMap(item.version)[field]) };
}

/**
 * What a restore does to each row of a list field (diffed whole), the rows paired by `keyOf`; `null` when the node
 * shows no field marks or the field is unchanged. A key that repeats is paired by its occurrence: the second row
 * with a key on the canvas with the second one in the version. Each change holds the whole items.
 */
export function keyedListRowChanges(
    diff: UnionNodeDiffState | null,
    field: FieldName,
    keyOf: (item: unknown) => string
): ListRowChanges | null {
    if (!showsFieldMarks(diff)) return null;
    const change = fieldChangeFor(diff, field);
    if (!change) return null;
    const current = keyedByOccurrence(asList(change.current), keyOf);
    const version = keyedByOccurrence(asList(change.version), keyOf);
    const rows = version.map(({ pairingKey, key, item }): MapKeyChange | null => {
        const currentItem = current.find((candidate) => candidate.pairingKey === pairingKey);
        if (!currentItem) return { key, status: 'added', current: null, version: item };
        return isSameValue(currentItem.item, item)
            ? null
            : { key, status: 'changed', current: currentItem.item, version: item };
    });
    const removed = current
        .filter(({ pairingKey }) => !version.some((candidate) => candidate.pairingKey === pairingKey))
        .map(({ key, item }): MapKeyChange => ({ key, status: 'deleted', current: item, version: null }));
    return { rows, removed };
}

/**
 * Whether a restore puts the rows of a list field (diffed whole) that both sides share, paired by `keyOf` as
 * `keyedListRowChanges` pairs them, in another order. Row marks cannot show this: a moved row may keep its value.
 * `false` when the node shows no field marks or the field is unchanged. Rows only one side has do not count.
 */
export function reordersKeyedList(
    diff: UnionNodeDiffState | null,
    field: FieldName,
    keyOf: (item: unknown) => string
): boolean {
    if (!showsFieldMarks(diff)) return false;
    const change = fieldChangeFor(diff, field);
    if (!change) return false;
    const current = keyedByOccurrence(asList(change.current), keyOf).map(({ pairingKey }) => pairingKey);
    const version = keyedByOccurrence(asList(change.version), keyOf).map(({ pairingKey }) => pairingKey);
    const inVersion = new Set(version);
    const inCurrent = new Set(current);
    const sharedInVersionOrder = version.filter((pairingKey) => inCurrent.has(pairingKey));
    return current
        .filter((pairingKey) => inVersion.has(pairingKey))
        .some((pairingKey, index) => pairingKey !== sharedInVersionOrder[index]);
}

/**
 * What a restore does to each item of a keyed collection (`tasks`, `condition_groups`), one change per item with
 * its changed fields gathered, in the diff's order (version items first); `null` when the node shows no field marks or
 * no item changed. An item a restore keeps has no change.
 */
export function keyedItemChanges(
    diff: UnionNodeDiffState | null,
    collection: KeyedCollectionName
): KeyedItemChange[] | null {
    if (diff === null || !showsFieldMarks(diff)) return null;
    const itemField = `${collection}[]`;
    const itemPathStart = `${collection}[${keyPrefixOf(collection) ?? ''}`;
    const items = new Map<string, KeyedItemChange>();
    for (const change of diff.fields) {
        if (change.field !== itemField && !change.field.startsWith(`${itemField}.`)) continue;
        // `tasks[].name` → `name`; the whole item → ''. The key is what the path holds between the item's brackets.
        const field = change.field.slice(itemField.length + 1);
        const pathEnd = field === '' ? ']' : `].${field}`;
        const key = change.path.slice(itemPathStart.length, change.path.length - pathEnd.length);
        if (field === '') {
            items.set(key, {
                key,
                status: change.status,
                fields: [],
                current: change.current,
                version: change.version,
            });
            continue;
        }
        const item = items.get(key);
        const fieldsSoFar = item?.status === 'changed' ? item : null;
        items.set(key, {
            key,
            status: 'changed',
            fields: [...(fieldsSoFar?.fields ?? []), field],
            current: { ...asMap(fieldsSoFar?.current), [field]: change.current },
            version: { ...asMap(fieldsSoFar?.version), [field]: change.version },
        });
    }
    return items.size > 0 ? [...items.values()] : null;
}

/**
 * One change for a field the panel shows as one value but the diff reports as several fields (e.g. the RAG picked,
 * its type and its id): each side as an object of those fields, or `null` when all of them are `null` (nothing
 * picked); `null` when the node shows no field marks or none of them changed. `shown` holds what the panel shows for
 * each field, which a field without a change has on both sides.
 */
export function fieldGroupChange(
    diff: UnionNodeDiffState | null,
    shown: Readonly<Partial<Record<FieldName, unknown>>>
): { current: Record<string, unknown> | null; version: Record<string, unknown> | null } | null {
    if (!showsFieldMarks(diff)) return null;
    const fields = Object.keys(shown) as FieldName[];
    const changes = fields.map((field) => fieldChangeFor(diff, field));
    if (changes.every((change) => change === null)) return null;
    const sideOf = (side: 'current' | 'version'): Record<string, unknown> | null => {
        const values = fields.map((field, index) => {
            const change = changes[index];
            // A side the restore sets to `null` is a value too, so only a field without a change shows `shown`.
            return change ? (change[side] ?? null) : (shown[field] ?? null);
        });
        return values.every((value) => value === null)
            ? null
            : Object.fromEntries(fields.map((field, index) => [field, values[index]]));
    };
    return { current: sideOf('current'), version: sideOf('version') };
}

/**
 * How a field holding the id of a linked entity (a flow, a trigger, a table) shows it: by the name `nameOf` finds
 * among the options the panel already loaded, else as `<kind> #<id>`, the words of the missing-reference notes.
 */
export function linkedEntityFormat(
    kind: string,
    nameOf: (id: unknown) => string | null | undefined
): (value: unknown) => string {
    return (value) => nameOf(value) ?? `${kind} #${String(value)}`;
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
 * - a field with a display formatter (`displayFormat`, else the field's own in `FIELD_DISPLAY`) shows the formatted
 *   text, struck as a whole when the formatted sides differ;
 * - any other value: `struckSegments`.
 * `field` is `null` for a change the caller worked out (e.g. one key of a map), which has no formatter.
 */
export function fieldValueSegments(
    field: FieldName | null,
    current: unknown,
    version: unknown,
    defaultValue?: unknown,
    displayFormat?: (value: unknown) => string
): DisplaySegment[] {
    const shown = (value: unknown): unknown => (value == null && defaultValue !== undefined ? defaultValue : value);
    const format = displayFormat ?? (field ? fieldFormat(field) : undefined);
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
 *   grapheme (what a reader sees as one character), so an emoji or an accent is never split. A long text is cut so
 *   the reader still sees where it is: always its start, then "…" and the context right before the struck part when
 *   there is a gap between the two, then the struck part, then the context right after it and "…" when more text
 *   follows. Each part is cut by graphemes and by lines, whichever cuts first (a line ends at a `\n`; `\r\n` is one
 *   break):
 *   - the start: `VALUE_START_LENGTH` graphemes, `VALUE_START_MAX_LINES` lines (or up to the struck part when that
 *     starts earlier);
 *   - the context before and after: `CHANGE_CONTEXT_LENGTH` graphemes, `CHANGE_CONTEXT_MAX_LINES` lines each,
 *     counting the line the struck part starts or ends on;
 *   - the struck part: longer than `STRUCK_PART_MAX_LENGTH` graphemes or `STRUCK_PART_MAX_LINES` lines, it keeps
 *     only its first and last `STRUCK_PART_KEPT_END` graphemes and `STRUCK_PART_KEPT_END_LINES` lines, with an
 *     unstruck "…" between them.
 *   A cut that would drop nothing but one line break is not made: "…" never stands for a line break alone;
 * - a list: the items the version does not have are struck; a repeated item is kept only as many times as the
 *   version has it. A long struck item is capped like a struck part of text, a long kept item cut like the start of
 *   a text;
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
        { text: keptBefore(before), struck: false },
        ...struckPart(current.slice(prefix, current.length - suffix)),
        { text: startOf(after, CHANGE_CONTEXT_LENGTH, CHANGE_CONTEXT_MAX_LINES), struck: false },
    ];
    return segments.filter((segment) => segment.text !== '');
}

/** The part a restore replaces, struck; only its two ends when it is long, the cut mark between them not struck. */
function struckPart(replaced: readonly string[]): DisplaySegment[] {
    if (replaced.length <= STRUCK_PART_MAX_LENGTH && lineCount(replaced) <= STRUCK_PART_MAX_LINES) {
        return [{ text: replaced.join(''), struck: true }];
    }
    // Over either limit the gap between the two ends holds at least 21 graphemes or 2 line breaks: never empty.
    const headEnd = Math.min(STRUCK_PART_KEPT_END, firstLinesEnd(replaced, STRUCK_PART_KEPT_END_LINES));
    const tailStart = Math.max(
        replaced.length - STRUCK_PART_KEPT_END,
        lastLinesStart(replaced, STRUCK_PART_KEPT_END_LINES)
    );
    return [
        { text: replaced.slice(0, headEnd).join(''), struck: true },
        { text: CUT_MARK, struck: false },
        { text: replaced.slice(tailStart).join(''), struck: true },
    ];
}

/**
 * The kept text before the struck part, which is the start of the value: whole when the start and the context
 * before the struck part meet, else the start, "…", and that context.
 */
function keptBefore(kept: readonly string[]): string {
    const startEnd = Math.min(VALUE_START_LENGTH, firstLinesEnd(kept, VALUE_START_MAX_LINES));
    const contextStart = Math.max(kept.length - CHANGE_CONTEXT_LENGTH, lastLinesStart(kept, CHANGE_CONTEXT_MAX_LINES));
    if (!isWorthCutting(kept.slice(startEnd, contextStart))) return kept.join('');
    return kept.slice(0, startEnd).join('') + CUT_MARK + kept.slice(contextStart).join('');
}

/** The first `length` graphemes and `maxLines` lines of a kept text, "…" after them when it is cut. */
function startOf(kept: readonly string[], length: number, maxLines: number): string {
    const end = Math.min(length, firstLinesEnd(kept, maxLines));
    return isWorthCutting(kept.slice(end)) ? kept.slice(0, end).join('') + CUT_MARK : kept.join('');
}

/** A "…" in place of nothing, or of one line break only, hides nothing: such a text is kept whole. */
function isWorthCutting(dropped: readonly string[]): boolean {
    return dropped.length > 1 || (dropped.length === 1 && !isLineBreak(dropped[0]));
}

/** Where the first `maxLines` lines end: at the `maxLines`-th line break (not kept), else at the end of the text. */
function firstLinesEnd(text: readonly string[], maxLines: number): number {
    let breaks = 0;
    for (let index = 0; index < text.length; index++) {
        if (isLineBreak(text[index]) && ++breaks === maxLines) return index;
    }
    return text.length;
}

/** Where the last `maxLines` lines start: right after the `maxLines`-th line break from the end, else at 0. */
function lastLinesStart(text: readonly string[], maxLines: number): number {
    let breaks = 0;
    for (let index = text.length - 1; index >= 0; index--) {
        if (isLineBreak(text[index]) && ++breaks === maxLines) return index + 1;
    }
    return 0;
}

function lineCount(text: readonly string[]): number {
    return text.filter(isLineBreak).length + 1;
}

/** `\r\n` is one grapheme, so it counts as one break. */
function isLineBreak(grapheme: string): boolean {
    return grapheme === '\n' || grapheme === '\r\n';
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
        const parts =
            match === -1
                ? struckPart(text)
                : [{ text: startOf(text, VALUE_START_LENGTH, VALUE_START_MAX_LINES), struck: false }];
        return index === 0 ? parts : [{ text: LIST_SEPARATOR, struck: false }, ...parts];
    });
}

function itemText(item: unknown): string {
    if (typeof item === 'string') return item;
    return item !== null && typeof item === 'object' ? stableStringify(item) : scalarText(item);
}

/** A pairing key per item: its own key and how many items before it had that key. */
function keyedByOccurrence(
    items: readonly unknown[],
    keyOf: (item: unknown) => string
): { pairingKey: string; key: string; item: unknown }[] {
    const seen = new Map<string, number>();
    return items.map((item) => {
        const key = keyOf(item);
        const occurrence = seen.get(key) ?? 0;
        seen.set(key, occurrence + 1);
        return { pairingKey: JSON.stringify([key, occurrence]), key, item };
    });
}

function asList(value: unknown): readonly unknown[] {
    return Array.isArray(value) ? value : [];
}

function jsonText(value: unknown): string {
    return value === undefined ? '' : JSON.stringify(value, null, 2);
}

function codeText(value: unknown): string {
    return typeof value === 'string' ? value : '';
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
