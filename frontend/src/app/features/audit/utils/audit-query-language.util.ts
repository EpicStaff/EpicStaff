import { AuditFilterNode, AuditFilterOp, FREE_TEXT_FIELD } from '../models/audit-filter.models';

// Port of the backend query-language parser (auditor filtering/query_language.py). The backend stays the
// authority for searching; this parse only maps query text into the Builder. One deliberate difference:
// values keep the exact text the user typed (numbers stay strings, e.g. "007"), because the Builder
// stores strings and must show values exactly as entered.

export class AuditQueryParseError extends Error {
    public override readonly name = 'AuditQueryParseError';
}

type TokenKind = 'STRING' | 'NUMBER' | 'OP' | 'LPAREN' | 'RPAREN' | 'LBRACKET' | 'RBRACKET' | 'COMMA' | 'IDENT' | 'EOF';

interface Token {
    kind: TokenKind;
    value: string;
    position: number;
}

const TOKEN_PATTERN =
    /(\s+)|("(?:[^"\\]|\\.)*")|(\d+(?:\.\d+)?)|(==|!=|>=|<=|!:|=|:|>|<)|(\()|(\))|(\[)|(\])|(,)|([A-Za-z_][A-Za-z0-9_.]*)/y;

const TOKEN_KINDS: (TokenKind | null)[] = [
    null,
    'STRING',
    'NUMBER',
    'OP',
    'LPAREN',
    'RPAREN',
    'LBRACKET',
    'RBRACKET',
    'COMMA',
    'IDENT',
];

const OP_ALIASES: Record<string, AuditFilterOp> = {
    '==': 'equals',
    '=': 'equals',
    '!=': 'not_equal',
    ':': 'contains',
    '!:': 'not_contains',
    '>': 'gt',
    '<': 'lt',
    '>=': 'gte',
    '<=': 'lte',
};

function tokenize(text: string): Token[] {
    const tokens: Token[] = [];
    let position = 0;
    while (position < text.length) {
        TOKEN_PATTERN.lastIndex = position;
        const match = TOKEN_PATTERN.exec(text);
        if (match === null) {
            throw new AuditQueryParseError(`Unexpected character "${text[position]}" at position ${position}`);
        }
        const kind = TOKEN_KINDS[match.slice(1).findIndex((group) => group !== undefined)];
        if (kind !== null) {
            tokens.push({ kind, value: match[0], position });
        }
        position += match[0].length;
    }
    tokens.push({ kind: 'EOF', value: '', position: text.length });
    return tokens;
}

function unquote(raw: string): string {
    return raw.slice(1, -1).replaceAll('\\"', '"');
}

class QueryParser {
    private index = 0;

    constructor(private readonly tokens: Token[]) {}

    public parse(): AuditFilterNode {
        const node = this.orExpression();
        const token = this.peek();
        if (token.kind !== 'EOF') {
            throw new AuditQueryParseError(`Unexpected trailing input "${token.value}" at position ${token.position}`);
        }
        return node;
    }

    private peek(): Token {
        return this.tokens[Math.min(this.index, this.tokens.length - 1)];
    }

    private advance(): Token {
        const token = this.peek();
        this.index++;
        return token;
    }

    private matchKeyword(keyword: string): boolean {
        const token = this.peek();
        if (token.kind === 'IDENT' && token.value.toLowerCase() === keyword) {
            this.advance();
            return true;
        }
        return false;
    }

    // consumes the keywords only if all of them follow, so a partial match still backtracks to free text
    private matchPhrase(...keywords: string[]): boolean {
        const matches = keywords.every((keyword, offset) => {
            const token = this.tokens[Math.min(this.index + offset, this.tokens.length - 1)];
            return token.kind === 'IDENT' && token.value.toLowerCase() === keyword;
        });
        if (matches) {
            this.index += keywords.length;
        }
        return matches;
    }

    private expectKeyword(keyword: string): void {
        if (!this.matchKeyword(keyword)) {
            const token = this.peek();
            throw new AuditQueryParseError(`Expected "${keyword}" at position ${token.position}, got "${token.value}"`);
        }
    }

    private orExpression(): AuditFilterNode {
        const children = [this.andExpression()];
        while (this.matchKeyword('or')) {
            children.push(this.andExpression());
        }
        return children.length === 1 ? children[0] : { op: 'or', children };
    }

    private andExpression(): AuditFilterNode {
        const children = [this.unary()];
        while (this.matchKeyword('and')) {
            children.push(this.unary());
        }
        return children.length === 1 ? children[0] : { op: 'and', children };
    }

    private unary(): AuditFilterNode {
        if (this.matchKeyword('not')) {
            return { op: 'not', child: this.unary() };
        }
        return this.atom();
    }

    private atom(): AuditFilterNode {
        if (this.peek().kind === 'LPAREN') {
            this.advance();
            const node = this.orExpression();
            if (this.peek().kind !== 'RPAREN') {
                throw new AuditQueryParseError(`Expected ")" at position ${this.peek().position}`);
            }
            this.advance();
            return node;
        }
        return this.comparisonOrFreeText();
    }

    private comparisonOrFreeText(): AuditFilterNode {
        const token = this.peek();
        if (token.kind !== 'IDENT') {
            return this.bareFreeText();
        }

        const saved = this.index;
        this.advance();
        const next = this.peek();

        if (token.value.toLowerCase() === 'text' && next.kind === 'OP' && next.value === ':') {
            this.advance();
            return { field: FREE_TEXT_FIELD, op: 'contains', value: this.value() };
        }

        const field = token.value;
        if (next.kind === 'OP') {
            this.advance();
            return { field, op: OP_ALIASES[next.value], value: this.value() };
        }
        if (this.matchKeyword('in')) {
            return { field, op: 'in', value: this.bracketedList() };
        }
        if (this.matchKeyword('not')) {
            if (this.matchKeyword('in')) {
                return { field, op: 'not_in', value: this.bracketedList() };
            }
            if (this.matchKeyword('exists')) {
                return { field, op: 'key_not_exists', value: null };
            }
            throw new AuditQueryParseError(`Expected "in" or "exists" after "not" at position ${this.peek().position}`);
        }
        if (this.matchKeyword('is')) {
            const negate = this.matchKeyword('not');
            this.expectKeyword('empty');
            return { field, op: negate ? 'is_not_empty' : 'is_empty', value: null };
        }
        if (this.matchPhrase('starts', 'with')) {
            return { field, op: 'starts_with', value: this.value() };
        }
        if (this.matchPhrase('ends', 'with')) {
            return { field, op: 'ends_with', value: this.value() };
        }
        if (this.matchKeyword('exists')) {
            return { field, op: 'key_exists', value: null };
        }

        // not a comparison (just a bare word) - backtrack and treat it as free text
        this.index = saved;
        return this.bareFreeText();
    }

    private bareFreeText(): AuditFilterNode {
        const token = this.advance();
        if (token.kind !== 'IDENT' && token.kind !== 'STRING' && token.kind !== 'NUMBER') {
            throw new AuditQueryParseError(`Unexpected token "${token.value}" at position ${token.position}`);
        }
        return {
            field: FREE_TEXT_FIELD,
            op: 'contains',
            value: token.kind === 'STRING' ? unquote(token.value) : token.value,
        };
    }

    private bracketedList(): string[] {
        const open = this.peek();
        if (open.kind !== 'LPAREN' && open.kind !== 'LBRACKET') {
            throw new AuditQueryParseError(`Expected "(" or "[" at position ${open.position}`);
        }
        const closing: TokenKind = open.kind === 'LPAREN' ? 'RPAREN' : 'RBRACKET';
        this.advance();
        const values = [this.value()];
        while (this.peek().kind === 'COMMA') {
            this.advance();
            values.push(this.value());
        }
        if (this.peek().kind !== closing) {
            throw new AuditQueryParseError(`Expected matching closing bracket at position ${this.peek().position}`);
        }
        this.advance();
        return values;
    }

    private value(): string {
        const token = this.advance();
        if (token.kind === 'STRING') {
            return unquote(token.value);
        }
        if (token.kind === 'NUMBER' || token.kind === 'IDENT') {
            return token.value;
        }
        throw new AuditQueryParseError(`Expected a value at position ${token.position}, got "${token.value}"`);
    }
}

// Throws AuditQueryParseError on invalid input.
export function parseAuditQuery(text: string): AuditFilterNode {
    if (text.trim() === '') {
        throw new AuditQueryParseError('Empty query');
    }
    return new QueryParser(tokenize(text)).parse();
}
