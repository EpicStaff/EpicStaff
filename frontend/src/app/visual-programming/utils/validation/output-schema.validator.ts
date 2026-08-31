/**
 * Frontend mirror of rules 1–3 of the backend's `validate_output_schema()`
 * (`src/django_app/tables/serializers/model_serializers/node_serializers/basic_node_serializers.py`),
 * attached identically to `TaskNodeSerializer.output_schema`, the nested
 * `AgentNodeTaskWriteSerializer.output_schema`, and the standalone `AgentNodeTaskSerializer`.
 *
 * Rules implemented here:
 *   1. `null`/`undefined` or `{}` → valid ("no schema").
 *   2. Not a plain object (e.g. an array, string, number) → invalid.
 *   3. An object without a top-level `"type"` key → invalid.
 */

const JSON_SCHEMA_SIMPLE_TYPES = new Set(['object', 'array', 'string', 'number', 'integer', 'boolean', 'null']);

function isValidTypeKeyword(value: unknown): boolean {
    if (typeof value === 'string') {
        return JSON_SCHEMA_SIMPLE_TYPES.has(value);
    }
    if (Array.isArray(value)) {
        return (
            value.length > 0 && value.every((entry) => typeof entry === 'string' && JSON_SCHEMA_SIMPLE_TYPES.has(entry))
        );
    }
    return false;
}

function isValidSubSchema(node: unknown): boolean {
    if (typeof node === 'boolean') {
        return true;
    }
    if (node == null || typeof node !== 'object' || Array.isArray(node)) {
        return false;
    }

    const obj = node as Record<string, unknown>;

    if ('type' in obj && !isValidTypeKeyword(obj['type'])) {
        return false;
    }

    if ('required' in obj) {
        const required = obj['required'];
        if (!Array.isArray(required) || !required.every((key) => typeof key === 'string')) {
            return false;
        }
    }

    const properties = obj['properties'];
    if (properties !== undefined) {
        if (properties == null || typeof properties !== 'object' || Array.isArray(properties)) {
            return false;
        }
        for (const value of Object.values(properties as Record<string, unknown>)) {
            if (!isValidSubSchema(value)) {
                return false;
            }
        }
    }

    const items = obj['items'];
    if (items !== undefined) {
        if (Array.isArray(items)) {
            if (!items.every((entry) => isValidSubSchema(entry))) {
                return false;
            }
        } else if (!isValidSubSchema(items)) {
            return false;
        }
    }

    return true;
}

export function isValidOutputSchema(value: unknown): boolean {
    // Rule 1: no schema at all is valid.
    if (value == null) return true;

    // Rule 2: must be a plain object (not an array, string, number, boolean, etc.).
    if (typeof value !== 'object' || Array.isArray(value)) return false;

    const obj = value as Record<string, unknown>;

    // Rule 1 (continued): an empty object means "no schema".
    if (Object.keys(obj).length === 0) return true;

    // Rule 3: a non-empty object must declare a top-level "type".
    if (!('type' in obj)) return false;

    return isValidSubSchema(obj);
}

/** User-facing copy for a rule 1–3 violation. Shown inline next to the Output Schema editor. */
export const OUTPUT_SCHEMA_RULE_ERROR =
    'Output Schema must be {} or a JSON Schema with a top-level "type" — one of object, array, string, ' +
    'number, integer, boolean, null (e.g. {"type": "object", ...}). "required" must be a list of names.';

/** User-facing copy for a draft that isn't parseable JSON at all. */
export const OUTPUT_SCHEMA_JSON_ERROR = 'Invalid JSON — fix the syntax; the current draft will not be saved.';
