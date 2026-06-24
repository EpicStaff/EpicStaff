/**
 * Pure-TS helper for bidirectional sync between the Expression column and
 * per-variable field_* columns in the Classification Decision Table grid.
 *
 * No Angular dependencies, no signals — fully unit-testable.
 */

export interface ParsedExpression {
    ok: boolean;
    parts: Record<string, string>; // varName -> opPart (e.g. "== 10", "> 0")
}

/** Operators that are allowed at the start of the "rest" part of a clause. */
const ALLOWED_OPERATORS = ['is not', 'is', 'not in', 'in', '==', '!=', '<=', '>=', '<', '>'];

/**
 * Insert spaces around comparison operators where missing so that expressions
 * like `variables.index<5` are treated the same as `variables.index < 5`.
 *
 * Multi-char operators are replaced before single-char ones so that `<=` is
 * never broken into `<` + `=`. After all replacements, runs of whitespace are
 * collapsed and the result is trimmed.
 *
 * Word-bounded operators (`is`, `is not`, `in`, `not in`) are left untouched —
 * they are only valid when written with natural spacing already.
 */
export function normalizeExpressionSpacing(input: string): string {
    if (!input) return input;
    let s = input;
    // Multi-char first (order matters: longest match wins)
    s = s.replace(/==/g, ' == ');
    s = s.replace(/!=/g, ' != ');
    s = s.replace(/<=/g, ' <= ');
    s = s.replace(/>=/g, ' >= ');
    // Single-char comparison ops — by this point all <= and >= are already
    // surrounded by spaces, so any remaining < or > is standalone.
    s = s.replace(/</g, ' < ');
    s = s.replace(/>/g, ' > ');
    // Collapse runs of whitespace and trim
    s = s.replace(/\s+/g, ' ').trim();
    return s;
}

/**
 * Convenience wrapper: normalise an operator part (the right-hand side typed
 * into a field cell, e.g. `<5` or `==10`) so callers receive `< 5` / `== 10`.
 */
export function normalizeOpPart(part: string): string {
    return normalizeExpressionSpacing(part).trim();
}

/**
 * Try to decompose a Python-ish boolean expression into per-variable AND clauses.
 * Returns ok:false if the expression can't be cleanly split (function calls, OR,
 * parens, arithmetic, etc.).
 *
 * `knownVarNames` is optional. When provided it is used only as a filter by the
 * caller — it does NOT gate validity here. Any syntactically valid
 * `variables.<name> <op> <value>` expression will return ok:true regardless of
 * whether <name> appears in knownVarNames.
 */
export function parseExpression(expression: string): ParsedExpression {
    const FAIL: ParsedExpression = { ok: false, parts: {} };

    const trimmed = expression?.trim();
    if (!trimmed) return FAIL;

    // Reject parentheses — function calls and grouping are out of scope
    if (trimmed.includes('(') || trimmed.includes(')')) return FAIL;

    // Reject OR as a word
    if (/\b(?:OR|or)\b/.test(trimmed)) return FAIL;

    // Reject commas — Python tuples / function args are out of scope
    if (trimmed.includes(',')) return FAIL;

    // Normalize spacing before further processing
    const normalized = normalizeExpressionSpacing(trimmed);

    // Split on AND / and as a word boundary
    const clauses = normalized.split(/\b(?:AND|and)\b/);

    const parts: Record<string, string> = {};

    for (const rawClause of clauses) {
        const clause = rawClause.trim();
        if (!clause) return FAIL;

        // Match: variables.<name> followed by optional whitespace then the rest.
        // \s* (not \s+) allows for cases where the operator is immediately adjacent
        // to the variable name before normalization has fully separated them.
        const match = clause.match(/^variables\.([A-Za-z_][A-Za-z0-9_]*)\s*(.+)$/);
        if (!match) return FAIL;

        const name = match[1];
        const rest = normalizeExpressionSpacing(match[2]).trim();

        // The rest must be a self-contained value — no further variable references
        if (/\bvariables\./.test(rest)) return FAIL;

        // The "rest" must start with an allowed operator
        const startsWithOp = ALLOWED_OPERATORS.some(
            (op) => rest === op || rest.startsWith(op + ' ') || rest.startsWith(op + '\t')
        );
        if (!startsWithOp) return FAIL;

        // Duplicate variable reference → bail out (ambiguous)
        if (Object.prototype.hasOwnProperty.call(parts, name)) return FAIL;

        parts[name] = rest;
    }

    return { ok: true, parts };
}

/**
 * Build an expression from per-variable parts by AND-joining
 * `variables.<name> <opPart>` for each non-empty entry.
 * `orderedVarNames` controls clause order so the result is stable.
 */
export function composeExpression(parts: Record<string, string>, orderedVarNames: string[]): string {
    const clauses: string[] = [];

    for (const name of orderedVarNames) {
        const part = parts[name]?.trim();
        if (part) {
            clauses.push(`variables.${name} ${normalizeExpressionSpacing(part)}`);
        }
    }

    return clauses.join(' and ');
}

export interface ParsedManipulation {
    ok: boolean;
    parts: Record<string, string>; // varName -> RHS verbatim (e.g. "variables.index + 1")
}

/**
 * Regex for a single assignment statement.
 * Matches: variables.<name> = <rhs>
 * The `=` must NOT be part of `==`, `!=`, `<=`, `>=`.
 * Lookbehind `(?<![=!<>])` ensures the `=` is standalone on the left,
 * and negative lookahead `(?!=)` ensures it is not followed by another `=`.
 */
const STATEMENT_RE = /^variables\.([A-Za-z_][A-Za-z0-9_]*)\s*(?<![=!<>])=(?!=)\s*(.+)$/;

/**
 * Try to decompose a manipulation string into per-variable assignment statements.
 * Returns ok:false if the manipulation can't be cleanly split (invalid syntax,
 * non-assignment operators, duplicate assignments, etc.).
 *
 * Statements are separated by semicolons. Trailing/empty statements are silently skipped.
 * The RHS is stored verbatim (Option A — no normalization).
 */
export function parseManipulation(manipulation: string): ParsedManipulation {
    const FAIL: ParsedManipulation = { ok: false, parts: {} };

    const trimmed = manipulation?.trim();
    if (!trimmed) return FAIL;

    const statements = trimmed
        .split(';')
        .map((s) => s.trim())
        .filter((s) => !!s);

    const parts: Record<string, string> = {};

    for (const statement of statements) {
        const match = statement.match(STATEMENT_RE);
        if (!match) return FAIL;

        const name = match[1];
        if (Object.prototype.hasOwnProperty.call(parts, name)) return FAIL;

        parts[name] = match[2].trim();
    }

    return { ok: true, parts };
}

/**
 * Build a manipulation string from per-variable parts by joining
 * `variables.<name> = <rhs>` statements with `; ` for each non-empty entry.
 * `orderedVarNames` controls statement order so the result is stable.
 */
export function composeManipulation(parts: Record<string, string>, orderedVarNames: string[]): string {
    const statements: string[] = [];

    for (const name of orderedVarNames) {
        const rhs = parts[name]?.trim();
        if (rhs) {
            statements.push(`variables.${name} = ${rhs}`);
        }
    }

    return statements.join('; ');
}

// ---------------------------------------------------------------------------
// Display-format conversion helpers
// These functions translate between the backend "stored" format
// (`variables.IDENT`) and the UI "display" format (`@IDENT`).
// All other helpers in this file operate exclusively on the stored format.
// ---------------------------------------------------------------------------

/**
 * Convert a stored expression (backend format) to display format for the UI.
 * Every `variables.IDENT` token is replaced with `@IDENT`.
 *
 * Regex used: /\bvariables\.([A-Za-z_][A-Za-z0-9_]*)/g
 */
export function toDisplayExpression(stored: string): string {
    if (!stored) return '';
    return stored.replace(/\bvariables\.([A-Za-z_][A-Za-z0-9_]*)/g, (_match, ident) => '@' + ident);
}

/**
 * Convert a display expression (UI format) back to stored format for the backend.
 * Every `@IDENT` token (not preceded by an identifier character) is replaced
 * with `variables.IDENT`.
 *
 * Regex used: /(?<![A-Za-z0-9_])@([A-Za-z_][A-Za-z0-9_]*)/g
 */
export function toStoredExpression(display: string): string {
    if (!display) return '';
    return display.replace(/(?<![A-Za-z0-9_])@([A-Za-z_][A-Za-z0-9_]*)/g, (_match, ident) => 'variables.' + ident);
}
