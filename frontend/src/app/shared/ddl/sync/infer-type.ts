import { isPrimitive } from '../core/ast';
import type { Schema } from '../core/resolver';
import type { JsonObject, JsonValue } from './json-value';

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;
const ISO_DATE_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$/;

/**
 * Called whenever `inferTypeText` resolves a plain-object value to a class
 * reference, so a caller (e.g. the merge algorithm) can ensure that class
 * actually gets declared/populated — without duplicating the type-inference
 * rules above.
 */
export type ClassReferenceHook = (className: string, key: string, value: JsonObject, isListElement: boolean) => void;

/**
 * Infer the DDL type source text for a JSON value discovered under `key`.
 * `key` is only consulted when `value` (or a nested array element) is a
 * plain object, to name the class it should reference — see
 * {@link classNameForKey}. `onClassReference`, if given, fires once per
 * object encountered so callers can act on the class name it produced.
 */
export function inferTypeText(value: JsonValue, key: string, schema: Schema, onClassReference?: ClassReferenceHook): string {
    return inferTypeTextForOccurrence(value, key, false, schema, onClassReference);
}

function inferTypeTextForOccurrence(
    value: JsonValue,
    key: string,
    isListElement: boolean,
    schema: Schema,
    onClassReference?: ClassReferenceHook
): string {
    if (value === null) return 'String?';
    if (typeof value === 'boolean') return 'Bool';
    if (typeof value === 'number') return Number.isInteger(value) ? 'Int' : 'Float';
    if (typeof value === 'string') return inferStringType(value);
    if (Array.isArray(value)) {
        if (value.length === 0) return '[String]';
        return `[${inferTypeTextForOccurrence(value[0], key, true, schema, onClassReference)}]`;
    }
    // Plain object: it becomes a reference to a (new or reused) class.
    const className = classNameForKey(key, isListElement, schema);
    onClassReference?.(className, key, value, isListElement);
    return className;
}

function inferStringType(value: string): string {
    if (DATE_ONLY.test(value)) return 'Date';
    if (ISO_DATE_TIME.test(value)) return 'DateTime';
    return 'String';
}

/**
 * Compute the class name a JSON object under `key` should reference:
 * PascalCase, singularized when the object is a list element, `Data`-suffixed
 * on a collision with a built-in primitive name, and — crucially — reused
 * verbatim when a class of that exact name already exists in `schema`. That
 * reuse rule is what makes repeated merges of the same JSON idempotent.
 */
export function classNameForKey(key: string, isListElement: boolean, schema: Schema): string {
    const singular = isListElement ? singularize(toPascalCase(key)) : toPascalCase(key);
    if (schema.classes.has(singular)) return singular;
    if (isPrimitive(singular)) return `${singular}Data`;
    return singular;
}

function toPascalCase(key: string): string {
    const words = key.split(/[^A-Za-z0-9]+/).filter((word) => word.length > 0);
    if (words.length === 0) return key;
    return words.map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join('');
}

function singularize(word: string): string {
    return word.length > 1 && word.endsWith('s') ? word.slice(0, -1) : word;
}
