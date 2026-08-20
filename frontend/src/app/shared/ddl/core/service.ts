import { PRIMITIVES, type TypeNode, isPrimitive, typeToString } from './ast';
import type { Span } from './diagnostics';
import type { Schema } from './resolver';

/**
 * Framework-agnostic language-intelligence helpers built on a resolved
 * {@link Schema}. Positions are 1-based line/column to match {@link Span}.
 *
 * These are consumed by the VS Code extension today and are intended to back a
 * web-app (Monaco) editor later — no editor APIs leak in here.
 */

export type SymbolCategory = 'class' | 'primitive' | 'unknown';

export interface SymbolAtResult {
    /** The identifier under the cursor. */
    name: string;
    /** Span of that identifier. */
    tokenSpan: Span;
    category: SymbolCategory;
    /** For a class, the span of its declaration name (go-to-definition target). */
    defSpan?: Span;
    /** True when the cursor sits on the class's own declaration name. */
    isDeclaration: boolean;
}

export interface CompletionItem {
    label: string;
    kind: 'class' | 'primitive';
    detail: string;
}

function spanContains(span: Span, line: number, col: number): boolean {
    return line === span.start.line && line === span.end.line && col >= span.start.col && col <= span.end.col;
}

/** Visit every `named` leaf inside a type expression. */
function eachNamed(t: TypeNode, cb: (name: string, span: Span) => void): void {
    switch (t.kind) {
        case 'named':
            cb(t.name, t.span);
            return;
        case 'list':
            eachNamed(t.element, cb);
            return;
        case 'optional':
            eachNamed(t.inner, cb);
            return;
    }
}

function categorize(name: string, schema: Schema): { category: SymbolCategory; defSpan?: Span } {
    if (isPrimitive(name)) return { category: 'primitive' };
    const decl = schema.classes.get(name);
    if (decl) return { category: 'class', defSpan: decl.nameSpan };
    return { category: 'unknown' };
}

/** Find the class/type identifier at a position, if any. */
export function symbolAt(schema: Schema, line: number, col: number): SymbolAtResult | undefined {
    for (const decl of schema.classes.values()) {
        if (spanContains(decl.nameSpan, line, col)) {
            return {
                name: decl.name,
                tokenSpan: decl.nameSpan,
                category: 'class',
                defSpan: decl.nameSpan,
                isDeclaration: true,
            };
        }
        if (decl.baseSpan && spanContains(decl.baseSpan, line, col)) {
            return {
                name: decl.base!,
                tokenSpan: decl.baseSpan,
                isDeclaration: false,
                ...categorize(decl.base!, schema),
            };
        }
        for (const prop of decl.properties) {
            const hit = namedHit(prop.type, schema, line, col);
            if (hit) return hit;
        }
    }
    for (const field of schema.domain?.fields ?? []) {
        const hit = namedHit(field.type, schema, line, col);
        if (hit) return hit;
    }
    return undefined;
}

function namedHit(type: TypeNode, schema: Schema, line: number, col: number): SymbolAtResult | undefined {
    let result: SymbolAtResult | undefined;
    eachNamed(type, (name, span) => {
        if (!result && spanContains(span, line, col)) {
            result = { name, tokenSpan: span, isDeclaration: false, ...categorize(name, schema) };
        }
    });
    return result;
}

const CLASS_HEADER_AWAITING_BASE = /^\s*class\s+\w+\s+(?:is(?:\s+an?)?)?\s*\w*$/;

/** Suggest completions for a given line of text (the text up to the cursor). */
export function completions(schema: Schema, lineText: string): CompletionItem[] {
    const classItems: CompletionItem[] = schema.order.map((name) => ({
        label: name,
        kind: 'class',
        detail: schema.classes.get(name)?.base ? `class · is a ${schema.classes.get(name)!.base}` : 'class',
    }));

    if (CLASS_HEADER_AWAITING_BASE.test(lineText)) {
        return classItems; // only classes make sense as a base
    }

    const primitiveItems: CompletionItem[] = PRIMITIVES.map((name) => ({
        label: name,
        kind: 'primitive',
        detail: 'built-in type',
    }));
    return [...primitiveItems, ...classItems];
}

/** Markdown describing a class: its base and full (flattened) property list. */
export function describeClass(schema: Schema, name: string): string | undefined {
    const decl = schema.classes.get(name);
    if (!decl) return undefined;
    const header = decl.base ? `**class ${name}** is a **${decl.base}**` : `**class ${name}**`;
    const props = (schema.flattened.get(name) ?? []).map((p) => `- \`${p.name}: ${typeToString(p.type)}\``);
    return props.length ? `${header}\n\n${props.join('\n')}` : header;
}

/** All names a reference could resolve to (for "did you mean" suggestions). */
export function knownTypeNames(schema: Schema): string[] {
    return [...PRIMITIVES, ...schema.order];
}

/** Closest candidate to `unknown` within a small edit distance, else undefined. */
export function suggestName(unknown: string, candidates: string[]): string | undefined {
    let best: string | undefined;
    let bestDistance = Infinity;
    for (const candidate of candidates) {
        const d = levenshtein(unknown.toLowerCase(), candidate.toLowerCase());
        if (d < bestDistance) {
            bestDistance = d;
            best = candidate;
        }
    }
    // Only suggest when it's a plausible typo, not an unrelated word.
    const threshold = Math.max(1, Math.floor(unknown.length / 2));
    return best && bestDistance <= threshold ? best : undefined;
}

function levenshtein(a: string, b: string): number {
    const rows = a.length + 1;
    const cols = b.length + 1;
    const dist: number[] = Array.from({ length: cols }, (_, j) => j);
    for (let i = 1; i < rows; i++) {
        let prev = dist[0]!;
        dist[0] = i;
        for (let j = 1; j < cols; j++) {
            const temp = dist[j]!;
            const cost = a[i - 1] === b[j - 1] ? 0 : 1;
            dist[j] = Math.min(dist[j]! + 1, dist[j - 1]! + 1, prev + cost);
            prev = temp;
        }
    }
    return dist[cols - 1]!;
}
