import { tokenize } from './lexer';
import { parse } from './parser';
import { type Schema, resolve } from './resolver';
import { emitJson } from './emitters/json';
import { emitTypeScript } from './emitters/typescript';
import { emitMermaid } from './emitters/mermaid';

export * from './ast';
export * from './diagnostics';
export type { Schema } from './resolver';
export { emitJson, emitTypeScript, emitMermaid };
export {
    symbolAt,
    completions,
    describeClass,
    knownTypeNames,
    suggestName,
    type SymbolAtResult,
    type SymbolCategory,
    type CompletionItem,
} from './service';

/** Parse and validate a schema source into a {@link Schema} model. */
export function compile(source: string): Schema {
    const { tokens, diagnostics: lexDiag } = tokenize(source);
    const { program, diagnostics: parseDiag } = parse(tokens);
    return resolve(program, [...lexDiag, ...parseDiag]);
}

export interface GenerateResult {
    schema: Schema;
    json: string;
    typescript: string;
    mermaid: string;
}

/**
 * One-call convenience for editors: compile the source and produce all three
 * outputs. Outputs are still generated when there are errors (best effort),
 * so a live preview keeps updating as the user types.
 */
export function generate(source: string): GenerateResult {
    const schema = compile(source);
    return {
        schema,
        json: emitJson(schema),
        typescript: emitTypeScript(schema),
        mermaid: emitMermaid(schema),
    };
}
