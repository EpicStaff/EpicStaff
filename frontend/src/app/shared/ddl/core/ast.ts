import type { Span } from './diagnostics';

/** The seven built-in scalar types the language understands. */
export const PRIMITIVES = ['Int', 'Float', 'Decimal', 'String', 'Bool', 'Date', 'DateTime'] as const;

export type PrimitiveName = (typeof PRIMITIVES)[number];

export function isPrimitive(name: string): name is PrimitiveName {
    return (PRIMITIVES as readonly string[]).includes(name);
}

/**
 * A type expression as written by the author. A bare identifier is a
 * `NamedType` here; the resolver decides later whether it is a primitive or a
 * reference to another class.
 */
export type TypeNode =
    | { kind: 'named'; name: string; span: Span }
    | { kind: 'list'; element: TypeNode; span: Span }
    | { kind: 'optional'; inner: TypeNode; span: Span };

export type LiteralKind = 'int' | 'float' | 'string' | 'bool' | 'null';

export interface Literal {
    kind: LiteralKind;
    /** The raw parsed value (number, string, boolean, or null). */
    value: number | string | boolean | null;
    span: Span;
}

export interface Property {
    name: string;
    type: TypeNode;
    /** Present only when the author wrote `= <literal>`. */
    default?: Literal;
    /** Trailing `# ...` doc comment, if any. */
    doc?: string;
    span: Span;
}

export interface ClassDecl {
    kind: 'class';
    name: string;
    /** Span of just the class-name token (for go-to-definition / hover). */
    nameSpan: Span;
    /** Name of the base class after `is a`, if any. Resolved later. */
    base?: string;
    baseSpan?: Span;
    properties: Property[];
    span: Span;
}

export interface DomainDecl {
    kind: 'domain';
    fields: Property[];
    span: Span;
}

export interface Program {
    classes: ClassDecl[];
    domain?: DomainDecl;
}

/** Render a type node back to its canonical source form (for diagrams/messages). */
export function typeToString(t: TypeNode): string {
    switch (t.kind) {
        case 'named':
            return t.name;
        case 'list':
            return `[${typeToString(t.element)}]`;
        case 'optional':
            return `${typeToString(t.inner)}?`;
    }
}
