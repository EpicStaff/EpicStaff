/**
 * Ghost placeholder shown inside the Output Schema `app-json-editor` (full mode only)
 * for Agent, Task, and Classification Decision Table (per-prompt) node panels
 */
export const OUTPUT_SCHEMA_EXAMPLE_HINT = `{
  "type": "object",
  "properties": {
    "example_string": { "type": "string" },
    "example_number": { "type": "number" },
    "example_array": {
      "type": "array",
      "items": { "type": "string" }
    }
  },
  "required": ["example_string", "example_number", "example_array"],
  "additionalProperties": false
}`;
