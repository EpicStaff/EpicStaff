import { isPrimitive, type PrimitiveName, type Property, type TypeNode } from '../core/ast';
import { compile } from '../core/index';
import type { Schema } from '../core/resolver';
import { inferTypeText } from './infer-type';
import type { JsonObject, JsonValue } from './json-value';

const IDENTIFIER_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;
const RESERVED_WORDS = new Set(['class', 'domain', 'true', 'false', 'null']);

export type SyncEntryKind = 'skipped-invalid-key' | 'skipped-empty-object' | 'type-mismatch' | 'removed-key' | 'discarded';

export interface SyncReportEntry {
    kind: SyncEntryKind;
    /** Dotted path to the JSON key this entry is about (root keys have no dot). */
    path: string;
    message: string;
}

export interface SyncReport {
    entries: SyncReportEntry[];
}

export interface MergeResult {
    updatedSource: string;
    changed: boolean;
    report: SyncReport;
}

/**
 * Additively merge `json` into `ddlSource`: new keys become new
 * properties/classes with inferred types; existing properties are never
 * retyped or deleted; keys removed from `json` are reported, not deleted.
 *
 * Precondition: `schema` must be the result of compiling `ddlSource` and must
 * have no errors (`!schema.hasErrors`) — the merge has nothing safe to anchor
 * edits to otherwise. As a safety net, the merged result is always recompiled
 * before being returned; if that introduces errors the edits are discarded
 * wholesale (`changed: false`) rather than corrupting the schema.
 */
export function mergeJsonIntoDdl(ddlSource: string, schema: Schema, json: JsonObject): MergeResult {
    if (schema.hasErrors) {
        return {
            updatedSource: ddlSource,
            changed: false,
            report: { entries: [{ kind: 'discarded', path: '', message: 'Schema has errors; merge was skipped.' }] },
        };
    }

    const context = new MergeContext(schema);
    if (schema.domain) {
        context.processObject(json, schema.domain.fields, { kind: 'domain-existing' }, '');
    } else {
        context.processObject(json, [], { kind: 'domain-new' }, '');
    }

    const updatedSource = context.buildUpdatedSource(ddlSource);
    if (updatedSource === ddlSource) {
        return { updatedSource: ddlSource, changed: false, report: { entries: context.reportEntries } };
    }

    const verification = compile(updatedSource);
    if (verification.hasErrors) {
        return {
            updatedSource: ddlSource,
            changed: false,
            report: {
                entries: [
                    ...context.reportEntries,
                    {
                        kind: 'discarded',
                        path: '',
                        message: 'Merge produced a source that failed to recompile; all edits were discarded.',
                    },
                ],
            },
        };
    }

    return { updatedSource, changed: true, report: { entries: context.reportEntries } };
}

type InsertTarget = { kind: 'domain-existing' } | { kind: 'domain-new' } | { kind: 'class'; name: string };

interface EditOp {
    afterLine: number;
    lines: string[];
}

interface PropertySpec {
    name: string;
    typeText: string;
}

interface PendingClass {
    name: string;
    properties: PropertySpec[];
}

type UnwrappedTypeNode = Extract<TypeNode, { kind: 'named' }> | Extract<TypeNode, { kind: 'list' }>;

/** Accumulates edits/report entries for a single merge pass. */
class MergeContext {
    readonly reportEntries: SyncReportEntry[] = [];

    private readonly edits: EditOp[] = [];
    private readonly pendingClasses = new Map<string, PendingClass>();
    private readonly pendingDomainFields: PropertySpec[] = [];
    private readonly failedClassNames = new Set<string>();

    constructor(private readonly schema: Schema) {}

    /** Walk one JSON object against the schema properties that describe it. */
    processObject(jsonObj: JsonObject, flatProps: Property[], target: InsertTarget, path: string): void {
        const flatByName = new Map(flatProps.map((prop) => [prop.name, prop] as const));

        for (const key of Object.keys(jsonObj)) {
            const value = jsonObj[key];
            const childPath = path ? `${path}.${key}` : key;
            const existing = flatByName.get(key);

            if (existing) {
                this.handleExistingProperty(existing, value, childPath);
                continue;
            }

            if (!isValidIdentifier(key)) {
                this.report('skipped-invalid-key', childPath, `'${key}' is not a valid DDL identifier and was skipped.`);
                continue;
            }

            this.addNewProperty(key, value, target, childPath);
        }

        for (const prop of flatProps) {
            if (!(prop.name in jsonObj)) {
                const removedPath = path ? `${path}.${prop.name}` : prop.name;
                this.report(
                    'removed-key',
                    removedPath,
                    `'${prop.name}' is declared in the schema but missing from the JSON; it was not deleted.`
                );
            }
        }
    }

    buildUpdatedSource(ddlSource: string): string {
        const eofLines = this.buildEofLines();
        if (this.edits.length === 0 && eofLines.length === 0) {
            return ddlSource;
        }

        const lines = ddlSource.split(/\r\n|\n/);
        const allEdits: EditOp[] = [...this.edits];
        if (eofLines.length > 0) {
            const endsWithBlankLine = lines.length > 0 && lines[lines.length - 1] === '';
            allEdits.push({ afterLine: lines.length, lines: endsWithBlankLine ? eofLines.slice(1) : eofLines });
        }

        return applyEdits(lines, allEdits, detectDominantEol(ddlSource));
    }

    private handleExistingProperty(prop: Property, value: JsonValue, path: string): void {
        const compatibility = this.checkCompatibility(prop, value);
        if (!compatibility.compatible) {
            this.report('type-mismatch', path, compatibility.reason);
            return;
        }
        if (value === null) return; // nothing to recurse into

        const declared = unwrapOptional(prop.type);
        if (declared.kind === 'list') {
            this.recurseIntoList(declared.element, value as JsonValue[], path);
            return;
        }
        if (!isPrimitive(declared.name)) {
            this.recurseIntoClass(declared.name, value as JsonObject, path);
        }
    }

    private recurseIntoList(elementType: TypeNode, values: JsonValue[], path: string): void {
        if (values.length === 0) return;
        const element = unwrapOptional(elementType);
        const first = values[0];
        if (element.kind === 'named' && !isPrimitive(element.name) && isPlainObject(first)) {
            this.recurseIntoClass(element.name, first, path);
        }
    }

    private recurseIntoClass(className: string, obj: JsonObject, path: string): void {
        const flatProps = this.schema.flattened.get(className) ?? [];
        this.processObject(obj, flatProps, { kind: 'class', name: className }, path);
    }

    private addNewProperty(key: string, value: JsonValue, target: InsertTarget, path: string): void {
        const typeText = this.computeTypeText(key, value, path);
        if (typeText === null) return; // already reported

        if (target.kind === 'domain-new') {
            this.pendingDomainFields.push({ name: key, typeText });
            return;
        }

        const anchorProperties =
            target.kind === 'domain-existing' ? this.schema.domain!.fields : this.schema.classes.get(target.name)!.properties;
        const anchor = anchorProperties[anchorProperties.length - 1]!;
        const indent = ' '.repeat(anchor.span.start.col - 1);
        this.edits.push({ afterLine: anchor.span.end.line, lines: [`${indent}${key}: ${typeText}`] });
    }

    /** Resolve the DDL type text for a new key, materializing any class it references as a side effect. */
    private computeTypeText(key: string, value: JsonValue, path: string): string | null {
        const failuresBefore = this.failedClassNames.size;
        const typeText = inferTypeText(value, key, this.schema, (className, hookKey, hookValue) =>
            this.ensureClassForReference(className, hookKey, hookValue, path)
        );
        return this.failedClassNames.size > failuresBefore ? null : typeText;
    }

    /** Make sure `className` exists (as a real class, an already-pending one, or a brand new one) and is populated from `value`. */
    private ensureClassForReference(className: string, key: string, value: JsonObject, path: string): void {
        if (this.schema.classes.has(className)) {
            const flatProps = this.schema.flattened.get(className) ?? [];
            this.processObject(value, flatProps, { kind: 'class', name: className }, path);
            return;
        }

        const pending = this.pendingClasses.get(className);
        if (pending) {
            this.mergeNewKeysIntoPendingClass(pending, value, path);
            return;
        }

        const properties: PropertySpec[] = [];
        for (const childKey of Object.keys(value)) {
            const childPath = `${path}.${childKey}`;
            if (!isValidIdentifier(childKey)) {
                this.report('skipped-invalid-key', childPath, `'${childKey}' is not a valid DDL identifier and was skipped.`);
                continue;
            }
            const typeText = this.computeTypeText(childKey, value[childKey], childPath);
            if (typeText === null) continue;
            properties.push({ name: childKey, typeText });
        }

        if (properties.length === 0) {
            this.report(
                'skipped-empty-object',
                path,
                `'${key}' has no properties that could become class '${className}' and was skipped.`
            );
            this.failedClassNames.add(className);
            return;
        }

        this.pendingClasses.set(className, { name: className, properties });
    }

    private mergeNewKeysIntoPendingClass(pending: PendingClass, value: JsonObject, path: string): void {
        const existingNames = new Set(pending.properties.map((p) => p.name));
        for (const childKey of Object.keys(value)) {
            if (existingNames.has(childKey)) continue;
            const childPath = `${path}.${childKey}`;
            if (!isValidIdentifier(childKey)) {
                this.report('skipped-invalid-key', childPath, `'${childKey}' is not a valid DDL identifier and was skipped.`);
                continue;
            }
            const typeText = this.computeTypeText(childKey, value[childKey], childPath);
            if (typeText === null) continue;
            pending.properties.push({ name: childKey, typeText });
        }
    }

    private checkCompatibility(prop: Property, value: JsonValue): { compatible: true } | { compatible: false; reason: string } {
        if (value === null) {
            if (prop.type.kind === 'optional') return { compatible: true };
            return { compatible: false, reason: `'${prop.name}' is required (not optional) but the JSON value is null.` };
        }

        const declared = unwrapOptional(prop.type);

        if (declared.kind === 'list') {
            if (!Array.isArray(value)) {
                return { compatible: false, reason: `'${prop.name}' is declared as a list but the JSON value is not an array.` };
            }
            return { compatible: true };
        }
        if (Array.isArray(value)) {
            return { compatible: false, reason: `'${prop.name}' is not declared as a list but the JSON value is an array.` };
        }

        if (!isPrimitive(declared.name)) {
            if (!isPlainObject(value)) {
                return {
                    compatible: false,
                    reason: `'${prop.name}' is declared as class '${declared.name}' but the JSON value is not an object.`,
                };
            }
            return { compatible: true };
        }

        if (isPlainObject(value)) {
            return { compatible: false, reason: `'${prop.name}' is declared as '${declared.name}' but the JSON value is an object.` };
        }
        const category = primitiveCategory(declared.name);
        const valueCategory = typeof value;
        if (valueCategory !== category) {
            return {
                compatible: false,
                reason: `'${prop.name}' is declared as '${declared.name}' but the JSON value is a ${valueCategory}.`,
            };
        }
        return { compatible: true };
    }

    private buildEofLines(): string[] {
        const blocks: string[][] = [];
        for (const pending of this.pendingClasses.values()) {
            blocks.push([`class ${pending.name}`, ...pending.properties.map((p) => `  ${p.name}: ${p.typeText}`)]);
        }
        if (this.pendingDomainFields.length > 0) {
            blocks.push(['domain', ...this.pendingDomainFields.map((p) => `  ${p.name}: ${p.typeText}`)]);
        }

        const lines: string[] = [];
        for (const block of blocks) lines.push('', ...block);
        return lines;
    }

    private report(kind: SyncEntryKind, path: string, message: string): void {
        this.reportEntries.push({ kind, path, message });
    }
}

function isValidIdentifier(key: string): boolean {
    return IDENTIFIER_RE.test(key) && !RESERVED_WORDS.has(key);
}

function isPlainObject(value: JsonValue): value is JsonObject {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function unwrapOptional(t: TypeNode): UnwrappedTypeNode {
    return t.kind === 'optional' ? unwrapOptional(t.inner) : t;
}

function primitiveCategory(name: PrimitiveName): 'number' | 'string' | 'boolean' {
    switch (name) {
        case 'Int':
        case 'Float':
        case 'Decimal':
            return 'number';
        case 'Bool':
            return 'boolean';
        case 'String':
        case 'Date':
        case 'DateTime':
            return 'string';
    }
}

function detectDominantEol(source: string): '\r\n' | '\n' {
    const crlfCount = (source.match(/\r\n/g) ?? []).length;
    const totalLineFeeds = (source.match(/\n/g) ?? []).length;
    const lfOnlyCount = totalLineFeeds - crlfCount;
    return crlfCount > lfOnlyCount ? '\r\n' : '\n';
}

function applyEdits(lines: string[], edits: EditOp[], eol: string): string {
    const grouped = new Map<number, string[]>();
    for (const edit of edits) {
        const existing = grouped.get(edit.afterLine) ?? [];
        existing.push(...edit.lines);
        grouped.set(edit.afterLine, existing);
    }

    const result = [...lines];
    const anchorsDescending = [...grouped.keys()].sort((a, b) => b - a);
    for (const afterLine of anchorsDescending) {
        result.splice(afterLine, 0, ...grouped.get(afterLine)!);
    }
    return result.join(eol);
}
