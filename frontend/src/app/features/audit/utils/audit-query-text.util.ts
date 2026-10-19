import { AuditFilterNode, AuditFilterOp, FREE_TEXT_FIELD } from '../models/audit-filter.models';

// Port of the backend ast_to_query_text (auditor filtering/query_language.py). Round-trips to a
// semantically identical filter, not byte-identical text (bracket style, operator alias may differ).

const OP_SYMBOLS: Partial<Record<AuditFilterOp, string>> = {
    equals: '=',
    not_equal: '!=',
    key_not_equals: '!=',
    contains: ':',
    not_contains: '!:',
    gt: '>',
    lt: '<',
    gte: '>=',
    lte: '<=',
};

const VALUE_FREE_SUFFIXES: Partial<Record<AuditFilterOp, string>> = {
    is_empty: 'is empty',
    is_not_empty: 'is not empty',
    key_exists: 'exists',
    key_not_exists: 'not exists',
};

function quote(value: unknown): string {
    if (typeof value === 'string') {
        return `"${value.replaceAll('"', '\\"')}"`;
    }
    if (typeof value === 'number') {
        return String(value);
    }
    throw new Error(`Cannot write value ${JSON.stringify(value)} as query text`);
}

function serialize(node: AuditFilterNode, isTopLevel: boolean): string {
    if ('children' in node) {
        const joined = node.children.map((child) => serialize(child, false)).join(` ${node.op} `);
        return isTopLevel ? joined : `(${joined})`;
    }
    if (node.op === 'not') {
        return `not ${serialize(node.child, false)}`;
    }

    const { field, op, value } = node;
    if (field === FREE_TEXT_FIELD) {
        return `text: ${quote(value)}`;
    }
    if (op === 'in' || op === 'not_in') {
        if (!Array.isArray(value)) {
            throw new Error(`Op "${op}" on field "${field}" needs a list value`);
        }
        return `${field} ${op === 'in' ? 'in' : 'not in'} (${value.map(quote).join(', ')})`;
    }
    const suffix = VALUE_FREE_SUFFIXES[op];
    if (suffix !== undefined) {
        return `${field} ${suffix}`;
    }
    if (op === 'starts_with' || op === 'ends_with') {
        return `${field} ${op === 'starts_with' ? 'starts with' : 'ends with'} ${quote(value)}`;
    }
    const symbol = OP_SYMBOLS[op];
    if (symbol === undefined) {
        throw new Error(`Op "${op}" on field "${field}" has no query-text form`);
    }
    return `${field} ${symbol} ${quote(value)}`;
}

// Inverse of parseAuditQuery - turns a Builder filter into query-language text.
export function auditFilterToQueryText(node: AuditFilterNode): string {
    return serialize(node, true);
}
