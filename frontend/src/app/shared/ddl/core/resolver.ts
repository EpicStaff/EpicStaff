import {
    type ClassDecl,
    type DomainDecl,
    type Literal,
    type Program,
    type Property,
    type TypeNode,
    isPrimitive,
} from './ast';
import { type Diagnostic, error, warning } from './diagnostics';

/**
 * A validated schema ready for the emitters. `flattened` holds each class's
 * full property list including inherited ones (base first, child overrides win).
 */
export interface Schema {
    classes: Map<string, ClassDecl>;
    /** Class names in declaration order. */
    order: string[];
    domain?: DomainDecl;
    flattened: Map<string, Property[]>;
    diagnostics: Diagnostic[];
    hasErrors: boolean;
}

export function resolve(program: Program, prior: Diagnostic[] = []): Schema {
    const diagnostics: Diagnostic[] = [...prior];
    const classes = new Map<string, ClassDecl>();
    const order: string[] = [];

    // 1. Register classes, catching duplicates.
    for (const c of program.classes) {
        if (classes.has(c.name)) {
            diagnostics.push(error('duplicate-class', `Class '${c.name}' is already defined.`, c.span));
            continue;
        }
        classes.set(c.name, c);
        order.push(c.name);
    }

    // 2. Validate bases, detect inheritance cycles.
    for (const c of program.classes) {
        if (c.base && !classes.has(c.base)) {
            diagnostics.push(error('unknown-base', `Base class '${c.base}' is not defined.`, c.baseSpan ?? c.span));
        }
    }
    detectCycles(classes, diagnostics);

    // 3. Validate every type reference and check duplicate property names locally.
    for (const c of classes.values()) {
        const seen = new Set<string>();
        for (const p of c.properties) {
            if (seen.has(p.name)) {
                diagnostics.push(
                    warning(
                        'duplicate-property',
                        `Property '${p.name}' is declared more than once in '${c.name}'.`,
                        p.span
                    )
                );
            }
            seen.add(p.name);
            checkType(p.type, classes, diagnostics);
            if (p.default) checkDefault(p, diagnostics);
        }
    }

    if (program.domain) {
        for (const f of program.domain.fields) {
            checkType(f.type, classes, diagnostics);
        }
    }

    // 4. Flatten inheritance (skip classes tangled in a cycle).
    const flattened = new Map<string, Property[]>();
    for (const name of order) flattened.set(name, flattenProperties(name, classes, diagnostics));

    return {
        classes,
        order,
        domain: program.domain,
        flattened,
        diagnostics,
        hasErrors: diagnostics.some((d) => d.severity === 'error'),
    };
}

function checkType(t: TypeNode, classes: Map<string, ClassDecl>, diagnostics: Diagnostic[]): void {
    switch (t.kind) {
        case 'named':
            if (!isPrimitive(t.name) && !classes.has(t.name)) {
                diagnostics.push(
                    error('unknown-type', `Type '${t.name}' is not a built-in type or a defined class.`, t.span)
                );
            }
            return;
        case 'list':
            checkType(t.element, classes, diagnostics);
            return;
        case 'optional':
            if (t.inner.kind === 'optional') {
                diagnostics.push(warning('double-optional', 'A type is marked optional twice.', t.span));
            }
            checkType(t.inner, classes, diagnostics);
            return;
    }
}

/** Light default-value type checking, mirroring the "coerce when safe" rule. */
function checkDefault(p: Property, diagnostics: Diagnostic[]): void {
    const base = baseTypeName(p.type);
    const def = p.default!;
    if (base === undefined) return; // list/class default checking is out of scope for now
    if (def.kind === 'null') {
        if (p.type.kind !== 'optional') {
            diagnostics.push(
                warning('null-default', `Property '${p.name}' has a null default but is not optional.`, def.span)
            );
        }
        return;
    }
    const ok = defaultMatches(base, def);
    if (!ok) {
        diagnostics.push(
            warning('default-type', `Default value for '${p.name}' does not obviously match type '${base}'.`, def.span)
        );
    }
}

function defaultMatches(base: string, def: Literal): boolean {
    switch (base) {
        case 'Int':
            return def.kind === 'int' || (def.kind === 'string' && /^-?\d+$/.test(String(def.value)));
        case 'Float':
        case 'Decimal':
            return def.kind === 'int' || def.kind === 'float';
        case 'String':
        case 'Date':
        case 'DateTime':
            return def.kind === 'string';
        case 'Bool':
            return def.kind === 'bool' || (def.kind === 'string' && /^(true|false)$/.test(String(def.value)));
        default:
            return true; // class-typed default: leave it alone
    }
}

/** The primitive/class name at the "head" of a type, unwrapping optional. */
function baseTypeName(t: TypeNode): string | undefined {
    if (t.kind === 'named') return t.name;
    if (t.kind === 'optional') return baseTypeName(t.inner);
    return undefined; // list
}

function detectCycles(classes: Map<string, ClassDecl>, diagnostics: Diagnostic[]): void {
    const state = new Map<string, 'visiting' | 'done'>();

    const visit = (name: string, path: string[]): void => {
        const s = state.get(name);
        if (s === 'done') return;
        if (s === 'visiting') {
            const cycle = [...path.slice(path.indexOf(name)), name].join(' -> ');
            const decl = classes.get(name);
            diagnostics.push(error('inheritance-cycle', `Inheritance cycle detected: ${cycle}.`, decl?.span));
            return;
        }
        state.set(name, 'visiting');
        const base = classes.get(name)?.base;
        if (base && classes.has(base)) visit(base, [...path, name]);
        state.set(name, 'done');
    };

    for (const name of classes.keys()) visit(name, []);
}

function flattenProperties(name: string, classes: Map<string, ClassDecl>, diagnostics: Diagnostic[]): Property[] {
    const chain: ClassDecl[] = [];
    const guard = new Set<string>();
    let current: ClassDecl | undefined = classes.get(name);
    while (current && !guard.has(current.name)) {
        guard.add(current.name);
        chain.unshift(current); // base-most first
        current = current.base ? classes.get(current.base) : undefined;
    }

    const result: Property[] = [];
    const index = new Map<string, number>();
    for (const c of chain) {
        for (const p of c.properties) {
            const existing = index.get(p.name);
            if (existing !== undefined)
                result[existing] = p; // child override wins, keeps position
            else {
                index.set(p.name, result.length);
                result.push(p);
            }
        }
    }
    return result;
}
