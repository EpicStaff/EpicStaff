/** The control a value is edited with: a schema names it in `x-widget`. */
export type SchemaWidget =
    | 'slider'
    | 'percent'
    | 'stepper'
    | 'toggle'
    | 'select'
    | 'chips'
    | 'list'
    | 'json'
    | 'text'
    | 'textarea'
    | 'secret';

export type JsonSchemaType = 'string' | 'number' | 'integer' | 'boolean' | 'array' | 'object' | 'null';

/**
 * One property of an object JSON Schema (draft 2020-12), with the UI hints the backend adds. Only the keywords the
 * frontend reads are listed.
 */
export interface JsonSchemaProperty {
    /** A list holding `'null'` means the value may be left "not set". */
    type: JsonSchemaType | JsonSchemaType[];
    title?: string;
    description?: string;
    /** `null`: "not set" by default. */
    default?: unknown;
    minimum?: number;
    maximum?: number;
    minLength?: number;
    pattern?: string;
    /** The allowed values; a `null` among them allows "not set". */
    enum?: (string | null)[];
    items?: { type: JsonSchemaType };
    'x-widget'?: SchemaWidget;
    /** The group the property is shown under; properties without one are not grouped. */
    'x-group'?: string;
    /** The increment of a slider or stepper. */
    'x-step'?: number;
    /** The factor the value is shown multiplied by, e.g. 100 for a percent. */
    'x-scale'?: number;
}

/** An object JSON Schema; properties come in display order. */
export interface JsonSchema {
    $schema?: string;
    type: 'object';
    properties: Record<string, JsonSchemaProperty>;
    required?: string[];
    additionalProperties?: boolean;
}

/** A server error for one field of a saved object, named by its dotted path, e.g. `parameters.temperature`. */
export interface SchemaFieldError {
    field: string;
    reason: string;
}
