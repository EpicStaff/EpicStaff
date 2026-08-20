import type { Literal, TypeNode } from '../ast';
import type { Schema } from '../resolver';

/** Sample scalar values used to make the JSON preview illustrative. */
const SAMPLES: Record<string, unknown> = {
    Int: 0,
    Float: 0,
    Decimal: 0,
    String: 'string',
    Bool: false,
    Date: '2025-01-01',
    DateTime: '2025-01-01T00:00:00Z',
};

/**
 * Build a sample JSON instance of the `domain` (or, if there is no domain, an
 * object with one sample per top-level class). Class cycles are broken with
 * `null` to keep generation finite.
 */
export function emitJson(schema: Schema): string {
    const root: Record<string, unknown> = {};

    if (schema.domain) {
        for (const f of schema.domain.fields) root[f.name] = sampleType(f.type, schema, new Set());
    } else {
        for (const name of schema.order) {
            root[lowerFirst(name)] = sampleClass(name, schema, new Set());
        }
    }

    return JSON.stringify(root, null, 2);
}

function sampleType(t: TypeNode, schema: Schema, path: Set<string>): unknown {
    switch (t.kind) {
        case 'optional':
            return sampleType(t.inner, schema, path);
        case 'list':
            return [sampleType(t.element, schema, path)];
        case 'named': {
            if (t.name in SAMPLES) return SAMPLES[t.name];
            if (schema.classes.has(t.name)) return sampleClass(t.name, schema, path);
            return null;
        }
    }
}

function sampleClass(name: string, schema: Schema, path: Set<string>): unknown {
    if (path.has(name)) return null; // recursive reference — stop here
    const next = new Set(path).add(name);
    const obj: Record<string, unknown> = {};
    for (const p of schema.flattened.get(name) ?? []) {
        obj[p.name] = p.default ? literalValue(p.default) : sampleType(p.type, schema, next);
    }
    return obj;
}

function literalValue(l: Literal): unknown {
    return l.value;
}

function lowerFirst(s: string): string {
    return s.length ? s[0]!.toLowerCase() + s.slice(1) : s;
}
