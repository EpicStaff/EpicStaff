/**
 * Reads and rewrites the parameter list of the top-level `def main(...)` of a Python node, so the panel can
 * keep its Input List and the signature in step. The sandbox calls `main(**inputs)`, so a row binds to the
 * parameter of the same name: names are matched by name, never by position. Pure text functions, no Angular.
 */

/** The parameters of `main()` an Input List row can bind to. */
export interface MainParameters {
    /** Named parameters in order; `*args`, `**kwargs`, bare `*` and `/` are not among them. */
    names: string[];
    /** `**kwargs` is present, so a row without a parameter of its name is still passed in. */
    acceptsAnyKeyword: boolean;
}

/** How one list of names became another. */
export interface NameChanges {
    renamed: { from: string; to: string }[];
    added: string[];
    removed: string[];
}

/** One comma-separated entry of the parameter list; `start`/`end` exclude surrounding whitespace and comments. */
interface ParameterEntry {
    /** `named` maps to an Input List row; `*args`, `**kwargs`, bare `*` and `/` never do. */
    kind: 'named' | 'other';
    name: string;
    start: number;
    end: number;
    hasDefault: boolean;
}

interface MainSignature {
    /** Offsets of the text between the parentheses. */
    listStart: number;
    listEnd: number;
    entries: ParameterEntry[];
}

// shortcut: a `def main(` at column 0 inside a module docstring is taken as the signature, and a lambda default
// (`f=lambda x, y: x`) splits at its comma (reads as `f`, `y`); scan for those first if they bite.
const MAIN_DEFINITION = /^def[ \t]+main[ \t]*\(/m;
const NAMED_ENTRY = /^([\p{L}_][\p{L}\p{N}_]*)\s*(?:[:=][\s\S]*)?$/u;
const IDENTIFIER = /^[\p{L}_][\p{L}\p{N}_]*$/u;
const PYTHON_KEYWORDS = new Set(
    (
        'False None True and as assert async await break class continue def del elif else except finally for ' +
        'from global if import in is lambda nonlocal not or pass raise return try while with yield'
    ).split(' ')
);
const DEFAULT_SEPARATOR = ', ';

/** The parameters of the top-level `main()`; null when it is missing, does not parse or repeats a name. */
export function parseMainParameters(code: string): MainParameters | null {
    const signature = parseMainSignature(code);
    if (!signature) return null;
    const names = namedEntries(signature).map((entry) => entry.name);
    if (new Set(names).size !== names.length) return null;
    return { names, acceptsAnyKeyword: signature.entries.some((entry) => code.startsWith('**', entry.start)) };
}

/** Each name could be a parameter: an identifier, not a Python keyword, not repeated. */
export function areValidParameterNames(names: readonly string[]): boolean {
    return (
        names.every((name) => IDENTIFIER.test(name) && !PYTHON_KEYWORDS.has(name)) &&
        new Set(names).size === names.length
    );
}

export function haveSameNames(names: readonly string[], other: readonly string[] | null): boolean {
    return other !== null && names.length === other.length && names.every((name, index) => name === other[index]);
}

/** The keys typed so far, trimmed, in order; a row whose key is still empty binds to nothing. */
export function namedKeys(rows: readonly { key?: string | null }[]): string[] {
    return rows.map((row) => (row.key ?? '').trim()).filter((key) => key !== '');
}

/**
 * The change from `previous` to `next`, by name: a name in both is untouched wherever it moved. The names that
 * left are paired with the names that came, in order, as renames; the rest are removed or added.
 */
export function diffNames(previous: readonly string[], next: readonly string[]): NameChanges {
    const left = previous.filter((name) => !next.includes(name));
    const came = next.filter((name) => !previous.includes(name));
    const pairs = Math.min(left.length, came.length);
    return {
        renamed: left.slice(0, pairs).map((from, index) => ({ from, to: came[index] })),
        removed: left.slice(pairs),
        added: came.slice(pairs),
    };
}

/**
 * What a signature edit does to the Input List. Without a signature seen before (it did not parse when the node
 * was opened), or with `**kwargs` taking any row, a row is never renamed or removed: new names only add rows.
 */
export function planInputListChanges(previous: readonly string[] | null, next: MainParameters): NameChanges {
    if (previous === null) return { renamed: [], removed: [], added: [...next.names] };
    const changes = diffNames(previous, next.names);
    if (!next.acceptsAnyKeyword) return changes;
    return { renamed: [], removed: [], added: [...changes.renamed.map((rename) => rename.to), ...changes.added] };
}

/**
 * Applies an Input List change to the `main()` parameter list only: a renamed parameter keeps its place, type
 * hint and default, a removed one goes with them, a new one is appended as a plain name after the last named
 * parameter (so before a trailing `*args` / `**kwargs`). The parameters never move. A change that does not
 * apply (no parameter of that name) or would leave invalid Python (a parameter without a default after one
 * with it, a bare `*` with nothing after it, a `/` with nothing before it) is skipped. Null when the code has
 * no parseable signature or a new name could not be a parameter.
 */
export function rewriteMainParameters(code: string, changes: NameChanges): string | null {
    const newNames = [...changes.renamed.map((rename) => rename.to), ...changes.added];
    if (!newNames.every((name) => areValidParameterNames([name])) || !parseMainSignature(code)) return null;

    let result = code;
    const apply = (edit: (current: string) => string | null): void => {
        const edited = edit(result);
        if (edited !== null && isValidSignature(edited)) result = edited;
    };
    changes.renamed.forEach(({ from, to }) => apply((current) => renameParameter(current, from, to)));
    changes.removed.forEach((name) => apply((current) => removeParameter(current, name)));
    changes.added.forEach((name) => apply((current) => appendParameter(current, name)));
    return result;
}

function renameParameter(code: string, from: string, to: string): string | null {
    const named = namedEntries(requireSignature(code));
    const entry = named.find((candidate) => candidate.name === from);
    if (!entry || named.some((candidate) => candidate.name === to)) return null;
    return splice(code, entry.start, entry.start + entry.name.length, to);
}

function removeParameter(code: string, name: string): string | null {
    const signature = requireSignature(code);
    const entries = signature.entries;
    const position = entries.findIndex((entry) => entry.kind === 'named' && entry.name === name);
    if (position === -1) return null;
    if (position + 1 < entries.length) return splice(code, entries[position].start, entries[position + 1].start, '');
    if (position > 0) return splice(code, entries[position - 1].end, entries[position].end, '');
    return splice(code, signature.listStart, signature.listEnd, '');
}

function appendParameter(code: string, name: string): string | null {
    const signature = requireSignature(code);
    const entries = signature.entries;
    const named = namedEntries(signature);
    if (named.some((entry) => entry.name === name)) return null;
    if (entries.length === 0) return splice(code, signature.listStart, signature.listEnd, name);

    const anchor = named.length > 0 ? entries.indexOf(named[named.length - 1]) : -1;
    if (anchor + 1 < entries.length) {
        const next = entries[anchor + 1];
        return splice(code, next.start, next.start, name + separatorAround(code, signature, anchor + 1));
    }
    return splice(code, entries[anchor].end, entries[anchor].end, separatorAround(code, signature, anchor) + name);
}

/** The comma and whitespace next to an entry, so an added parameter follows the existing one-per-line or inline layout. */
function separatorAround(code: string, signature: MainSignature, position: number): string {
    const entries = signature.entries;
    const separator =
        position + 1 < entries.length
            ? code.slice(entries[position].end, entries[position + 1].start)
            : position > 0
              ? code.slice(entries[position - 1].end, entries[position].start)
              : ',' + code.slice(signature.listStart, entries[position].start);
    // Keep only the line break and indentation: a comment stays with its own parameter instead of being copied.
    return separator.includes('\n') ? ',' + separator.slice(separator.lastIndexOf('\n')) : DEFAULT_SEPARATOR;
}

/** The rules a rewrite could break: defaults order before `*`, a bare `*` needs a name after it, `/` one before. */
function isValidSignature(code: string): boolean {
    const signature = parseMainSignature(code);
    if (!signature) return false;
    const entries = signature.entries;
    let seenDefault = false;
    let keywordOnly = false;
    for (const [position, entry] of entries.entries()) {
        const text = code.slice(entry.start, entry.end);
        if (text === '/' && (position === 0 || keywordOnly)) return false;
        if (text === '*' && entries[position + 1]?.kind !== 'named') return false;
        if (text.startsWith('*')) keywordOnly = true;
        if (entry.kind !== 'named' || keywordOnly) continue;
        if (seenDefault && !entry.hasDefault) return false;
        seenDefault = seenDefault || entry.hasDefault;
    }
    return true;
}

function namedEntries(signature: MainSignature): ParameterEntry[] {
    return signature.entries.filter((entry) => entry.kind === 'named');
}

/** Only called on code that was just parsed, or produced from parsed code by one edit. */
function requireSignature(code: string): MainSignature {
    const signature = parseMainSignature(code);
    if (!signature) throw new Error('The main() signature stopped parsing after an edit.');
    return signature;
}

function splice(text: string, start: number, end: number, insertion: string): string {
    return text.slice(0, start) + insertion + text.slice(end);
}

interface EntryBounds {
    start: number;
    end: number;
    hasDefault: boolean;
}

/** Splits the parameter list at its top-level commas, skipping brackets, strings and comments. */
function parseMainSignature(code: string): MainSignature | null {
    const definition = MAIN_DEFINITION.exec(code);
    if (!definition) return null;
    const listStart = definition.index + definition[0].length;

    const bounds: EntryBounds[] = [];
    let current: EntryBounds = { start: -1, end: -1, hasDefault: false };
    let depth = 0;
    let index = listStart;
    const closeEntry = (): void => {
        bounds.push(current);
        current = { start: -1, end: -1, hasDefault: false };
    };
    const markSignificant = (start: number, end: number): void => {
        if (current.start === -1) current.start = start;
        current.end = end;
    };

    while (index < code.length) {
        const character = code[index];
        if (character === '#') {
            const lineEnd = code.indexOf('\n', index);
            index = lineEnd === -1 ? code.length : lineEnd;
            continue;
        }
        if (character === '"' || character === "'") {
            const stringEnd = findStringEnd(code, index);
            if (stringEnd === -1) return null;
            markSignificant(index, stringEnd);
            index = stringEnd;
            continue;
        }
        if (character === '(' || character === '[' || character === '{') {
            depth++;
        } else if (character === ')' || character === ']' || character === '}') {
            if (depth === 0) {
                if (character !== ')') return null;
                closeEntry();
                return buildSignature(code, listStart, index, bounds);
            }
            depth--;
        } else if (character === ',' && depth === 0) {
            closeEntry();
            index++;
            continue;
        } else if (character === '=' && depth === 0) {
            current.hasDefault = true;
        }
        if (!/\s/.test(character)) markSignificant(index, index + 1);
        index++;
    }
    return null;
}

function buildSignature(code: string, listStart: number, listEnd: number, bounds: EntryBounds[]): MainSignature | null {
    // Only the last entry may be empty: `main()` or a trailing comma.
    const lastBound = bounds[bounds.length - 1];
    const filled = lastBound.start === -1 ? bounds.slice(0, -1) : bounds;
    if (filled.some((bound) => bound.start === -1)) return null;

    const entries: ParameterEntry[] = [];
    for (const { start, end, hasDefault } of filled) {
        const text = code.slice(start, end);
        if (text === '/' || text.startsWith('*')) {
            entries.push({ kind: 'other', name: '', start, end, hasDefault });
            continue;
        }
        const match = NAMED_ENTRY.exec(text);
        if (!match) return null;
        entries.push({ kind: 'named', name: match[1], start, end, hasDefault });
    }
    return { listStart, listEnd, entries };
}

/** The index just past the string literal opening at `start`, or -1 when it is not closed yet. */
function findStringEnd(code: string, start: number): number {
    const quote = code[start];
    const delimiter = code.startsWith(quote.repeat(3), start) ? quote.repeat(3) : quote;
    let index = start + delimiter.length;
    while (index < code.length) {
        if (code[index] === '\\') {
            index += 2;
            continue;
        }
        if (code.startsWith(delimiter, index)) return index + delimiter.length;
        if (delimiter.length === 1 && code[index] === '\n') return -1;
        index++;
    }
    return -1;
}
