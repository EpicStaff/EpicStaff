import { type Literal, type Property, type TypeNode } from '../ast';
import type { Schema } from '../resolver';

const TS_PRIMITIVES: Record<string, string> = {
    Int: 'number',
    Float: 'number',
    Decimal: 'number',
    String: 'string',
    Bool: 'boolean',
    Date: 'string',
    DateTime: 'string',
};

/** Emit real TypeScript classes (with `extends` for inheritance). */
export function emitTypeScript(schema: Schema): string {
    const blocks: string[] = [];

    for (const name of schema.order) {
        const c = schema.classes.get(name)!;
        const heading = c.base ? `export class ${name} extends ${c.base} {` : `export class ${name} {`;
        const lines = c.properties.map((p) => '  ' + tsField(p));
        blocks.push([heading, ...lines, '}'].join('\n'));
    }

    if (schema.domain) {
        const lines = schema.domain.fields.map((f) => '  ' + tsField(f));
        blocks.push(['export class Domain {', ...lines, '}'].join('\n'));
    }

    return blocks.join('\n\n') + '\n';
}

function tsField(p: Property): string {
    const optional = p.type.kind === 'optional';
    const typeText = tsType(p.type);
    if (p.default) {
        return `${p.name}: ${typeText} = ${tsLiteral(p.default)};`;
    }
    // `!` asserts required fields are initialised elsewhere; `?` marks optionals.
    return optional ? `${p.name}?: ${typeText};` : `${p.name}!: ${typeText};`;
}

function tsType(t: TypeNode): string {
    switch (t.kind) {
        case 'named':
            return TS_PRIMITIVES[t.name] ?? t.name;
        case 'list': {
            const inner = tsType(t.element);
            return /[|&]/.test(inner) ? `(${inner})[]` : `${inner}[]`;
        }
        case 'optional':
            return `${tsType(t.inner)} | null`;
    }
}

function tsLiteral(l: Literal): string {
    if (l.kind === 'string') return JSON.stringify(l.value);
    if (l.kind === 'null') return 'null';
    return String(l.value);
}
