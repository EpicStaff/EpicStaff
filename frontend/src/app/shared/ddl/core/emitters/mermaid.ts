import type { TypeNode } from '../ast';
import type { Schema } from '../resolver';

/**
 * Emit a Mermaid `classDiagram`: a box per class with its own properties,
 * `<|--` edges for inheritance, and `-->` edges for class-typed properties
 * (associations). A `domain` becomes a `Domain` box wired to its field types.
 */
export function emitMermaid(schema: Schema): string {
    const lines: string[] = ['classDiagram'];
    const relations: string[] = [];

    for (const name of schema.order) {
        const c = schema.classes.get(name)!;
        lines.push(`  class ${name} {`);
        for (const p of c.properties) {
            lines.push(`    +${mermaidType(p.type)} ${p.name}`);
        }
        lines.push('  }');

        if (c.base) relations.push(`  ${c.base} <|-- ${name}`);
        for (const p of c.properties) {
            const target = referencedClass(p.type, schema);
            if (target) relations.push(`  ${name} --> "${cardinality(p.type)}" ${target} : ${p.name}`);
        }
    }

    if (schema.domain) {
        lines.push('  class Domain {');
        for (const f of schema.domain.fields) lines.push(`    +${mermaidType(f.type)} ${f.name}`);
        lines.push('  }');
        for (const f of schema.domain.fields) {
            const target = referencedClass(f.type, schema);
            if (target) relations.push(`  Domain --> "${cardinality(f.type)}" ${target} : ${f.name}`);
        }
    }

    return [...lines, ...relations].join('\n') + '\n';
}

/** Mermaid-safe type label: lists become `List~T~`, optionals get a `?`. */
function mermaidType(t: TypeNode): string {
    switch (t.kind) {
        case 'named':
            return t.name;
        case 'list':
            return `List~${mermaidType(t.element)}~`;
        case 'optional':
            return `${mermaidType(t.inner)}?`;
    }
}

function cardinality(t: TypeNode): string {
    if (t.kind === 'list') return '*';
    if (t.kind === 'optional') return '0..1';
    return '1';
}

/** If the type ultimately points at a user class, return its name. */
function referencedClass(t: TypeNode, schema: Schema): string | undefined {
    switch (t.kind) {
        case 'named':
            return schema.classes.has(t.name) ? t.name : undefined;
        case 'list':
            return referencedClass(t.element, schema);
        case 'optional':
            return referencedClass(t.inner, schema);
    }
}
