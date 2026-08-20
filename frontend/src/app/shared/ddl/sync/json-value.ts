/**
 * A minimal, framework-free JSON value model shared by the DDL⇄JSON sync
 * helpers. Deliberately narrower than `unknown`/`any` so every branch that
 * inspects a value is exhaustive and type-checked.
 */
export type JsonValue = string | number | boolean | null | JsonValue[] | JsonObject;

export interface JsonObject {
    [key: string]: JsonValue;
}
