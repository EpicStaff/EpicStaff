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
 *
 * Rule 4 (full JSON-Schema meta-validation via the `jsonschema` library) is intentionally
 * NOT replicated here — a frontend check stricter than the server would block saves the
 * server would otherwise accept, which is worse than the 400 this predicate prevents.
 * That rule stays server-side.
 */
export function isValidOutputSchema(value: unknown): boolean {
    // Rule 1: no schema at all is valid.
    if (value == null) return true;

    // Rule 2: must be a plain object (not an array, string, number, boolean, etc.).
    if (typeof value !== 'object' || Array.isArray(value)) return false;

    const obj = value as Record<string, unknown>;

    // Rule 1 (continued): an empty object means "no schema".
    if (Object.keys(obj).length === 0) return true;

    // Rule 3: a non-empty object must declare a top-level "type".
    return 'type' in obj;
}

/** User-facing copy for a rule 1–3 violation. Shown inline next to the Output Schema editor. */
export const OUTPUT_SCHEMA_RULE_ERROR =
    'Output Schema must be {} or a JSON Schema with a top-level "type" (e.g. {"type": "object", ...}).';

/** User-facing copy for a draft that isn't parseable JSON at all. */
export const OUTPUT_SCHEMA_JSON_ERROR = 'Invalid JSON — fix the syntax; the current draft will not be saved.';
