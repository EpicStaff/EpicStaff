import { type Diagnostic, type Span, error } from './diagnostics';

export type TokenType =
    | 'class'
    | 'domain'
    | 'ident'
    | 'colon'
    | 'lbracket'
    | 'rbracket'
    | 'question'
    | 'equals'
    | 'int'
    | 'float'
    | 'string'
    | 'bool'
    | 'null'
    | 'newline'
    | 'indent'
    | 'dedent'
    | 'eof';

export interface Token {
    type: TokenType;
    /** The literal source text (for string tokens, the decoded value). */
    value: string;
    span: Span;
}

const KEYWORDS = new Set(['class', 'domain']);

/**
 * Remove a trailing `# ...` comment from a single line without breaking inside
 * a double-quoted string. Length is preserved up to the cut so column numbers
 * stay accurate.
 */
function stripComment(line: string): string {
    let inString = false;
    for (let i = 0; i < line.length; i++) {
        const c = line[i];
        if (c === '"' && line[i - 1] !== '\\') inString = !inString;
        else if (c === '#' && !inString) return line.slice(0, i);
    }
    return line;
}

/** Turn source text into a flat token stream with INDENT/DEDENT markers. */
export function tokenize(source: string): {
    tokens: Token[];
    diagnostics: Diagnostic[];
} {
    const tokens: Token[] = [];
    const diagnostics: Diagnostic[] = [];
    const indentStack: number[] = [0];
    const rawLines = source.split(/\r?\n/);

    const push = (type: TokenType, value: string, line: number, startCol: number, endCol: number) =>
        tokens.push({ type, value, span: { start: { line, col: startCol }, end: { line, col: endCol } } });

    for (let i = 0; i < rawLines.length; i++) {
        const lineNo = i + 1;
        const raw = rawLines[i] ?? '';
        const code = stripComment(raw);

        if (code.trim() === '') continue; // blank or comment-only line: no structural effect

        // Measure indentation (leading whitespace). Tabs are discouraged.
        let indent = 0;
        while (indent < code.length && (code[indent] === ' ' || code[indent] === '\t')) {
            if (code[indent] === '\t') {
                diagnostics.push(
                    error('tab-indent', 'Use spaces, not tabs, for indentation.', {
                        start: { line: lineNo, col: indent + 1 },
                        end: { line: lineNo, col: indent + 2 },
                    })
                );
            }
            indent++;
        }

        const top = indentStack[indentStack.length - 1] ?? 0;
        if (indent > top) {
            indentStack.push(indent);
            push('indent', '', lineNo, 1, indent + 1);
        } else {
            while (indent < (indentStack[indentStack.length - 1] ?? 0)) {
                indentStack.pop();
                push('dedent', '', lineNo, 1, 1);
            }
            if (indent !== (indentStack[indentStack.length - 1] ?? 0)) {
                diagnostics.push(
                    error('bad-indent', 'Indentation does not match any enclosing block.', {
                        start: { line: lineNo, col: 1 },
                        end: { line: lineNo, col: indent + 1 },
                    })
                );
            }
        }

        tokenizeLine(code, indent, lineNo, push, diagnostics);
        push('newline', '', lineNo, code.length + 1, code.length + 1);
    }

    // Close any open blocks at end of file.
    const lastLine = rawLines.length;
    while ((indentStack.length ?? 0) > 1) {
        indentStack.pop();
        push('dedent', '', lastLine, 1, 1);
    }
    push('eof', '', lastLine, 1, 1);

    return { tokens, diagnostics };
}

function tokenizeLine(
    code: string,
    start: number,
    lineNo: number,
    push: (type: TokenType, value: string, line: number, startCol: number, endCol: number) => void,
    diagnostics: Diagnostic[]
): void {
    let i = start;
    const isIdentStart = (c: string) => /[A-Za-z_]/.test(c);
    const isIdent = (c: string) => /[A-Za-z0-9_]/.test(c);
    const isDigit = (c: string) => c >= '0' && c <= '9';

    while (i < code.length) {
        const c = code[i]!;

        if (c === ' ' || c === '\t') {
            i++;
            continue;
        }

        const col = i + 1;

        if (isIdentStart(c)) {
            let j = i + 1;
            while (j < code.length && isIdent(code[j]!)) j++;
            const word = code.slice(i, j);
            if (KEYWORDS.has(word)) push(word as TokenType, word, lineNo, col, j + 1);
            else if (word === 'true' || word === 'false') push('bool', word, lineNo, col, j + 1);
            else if (word === 'null') push('null', word, lineNo, col, j + 1);
            else push('ident', word, lineNo, col, j + 1);
            i = j;
            continue;
        }

        if (isDigit(c) || (c === '-' && isDigit(code[i + 1] ?? ''))) {
            let j = i + 1;
            let isFloat = false;
            while (j < code.length && isDigit(code[j]!)) j++;
            if (code[j] === '.' && isDigit(code[j + 1] ?? '')) {
                isFloat = true;
                j++;
                while (j < code.length && isDigit(code[j]!)) j++;
            }
            push(isFloat ? 'float' : 'int', code.slice(i, j), lineNo, col, j + 1);
            i = j;
            continue;
        }

        if (c === '"') {
            let j = i + 1;
            let value = '';
            while (j < code.length && code[j] !== '"') {
                if (code[j] === '\\' && j + 1 < code.length) {
                    const next = code[j + 1]!;
                    value += next === 'n' ? '\n' : next === 't' ? '\t' : next;
                    j += 2;
                } else {
                    value += code[j];
                    j++;
                }
            }
            if (j >= code.length) {
                diagnostics.push(
                    error('unterminated-string', 'String is missing a closing quote.', {
                        start: { line: lineNo, col },
                        end: { line: lineNo, col: j + 1 },
                    })
                );
            }
            push('string', value, lineNo, col, j + 2);
            i = j + 1;
            continue;
        }

        const single: Record<string, TokenType> = {
            ':': 'colon',
            '[': 'lbracket',
            ']': 'rbracket',
            '?': 'question',
            '=': 'equals',
        };
        if (single[c]) {
            push(single[c]!, c, lineNo, col, col + 1);
            i++;
            continue;
        }

        diagnostics.push(
            error('unexpected-char', `Unexpected character '${c}'.`, {
                start: { line: lineNo, col },
                end: { line: lineNo, col: col + 1 },
            })
        );
        i++;
    }
}
