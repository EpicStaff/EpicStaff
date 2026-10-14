import type { AuditFilterChipPart } from './describe-audit-filter.util';

// Mirrors the backend query-language tokenizer (auditor filtering/query_language.py); `OTHER` catches
// anything it would reject, so a half-typed query still renders.
const TOKEN_PATTERN =
    /(\s+)|("(?:[^"\\]|\\.)*")|(\d+(?:\.\d+)?)|(==|!=|>=|<=|!:|=|:|>|<)|([A-Za-z_][A-Za-z0-9_.]*)|([\s\S])/g;

const KEYWORDS = new Set(['and', 'or', 'not', 'in', 'is', 'empty']);
// an identifier followed by one of these is a field name, not a value
const FIELD_FOLLOWERS = new Set(['in', 'is', 'not']);

interface QueryToken {
    text: string;
    kind: 'space' | 'string' | 'number' | 'operator' | 'identifier' | 'other';
}

const TOKEN_KINDS: QueryToken['kind'][] = ['space', 'string', 'number', 'operator', 'identifier', 'other'];

function tokenize(query: string): QueryToken[] {
    return Array.from(query.matchAll(TOKEN_PATTERN), (match) => ({
        text: match[0],
        kind: TOKEN_KINDS[match.slice(1).findIndex((group) => group !== undefined)],
    }));
}

function isFieldName(tokens: QueryToken[], index: number): boolean {
    const next = tokens.slice(index + 1).find((token) => token.kind !== 'space');
    return (
        next !== undefined &&
        (next.kind === 'operator' || (next.kind === 'identifier' && FIELD_FOLLOWERS.has(next.text.toLowerCase())))
    );
}

// Splits a query into parts, marking field names, operators and keywords for highlighting; values stay plain.
export function highlightQuery(query: string): AuditFilterChipPart[] {
    const tokens = tokenize(query);
    return tokens.map((token, index) => ({
        text: token.text,
        isKeyword:
            token.kind === 'operator' ||
            (token.kind === 'identifier' && (KEYWORDS.has(token.text.toLowerCase()) || isFieldName(tokens, index))),
    }));
}
