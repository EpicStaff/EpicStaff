import { QUERY_EXAMPLES } from '../models/audit-filter-options';
import { AuditQueryParseError, parseAuditQuery } from './audit-query-language.util';

const text = (value: string) => ({ field: '__text__', op: 'contains', value });

describe('parseAuditQuery', () => {
    it('parses the query examples shown in the panel', () => {
        expect(QUERY_EXAMPLES.map(parseAuditQuery)).toEqual([
            {
                op: 'and',
                children: [
                    { field: 'status', op: 'in', value: ['failed'] },
                    { field: 'node_type', op: 'in', value: ['AGENT', 'PYTHON'] },
                ],
            },
            { field: 'name', op: 'equals', value: 'Session Start' },
            {
                op: 'and',
                children: [
                    { field: 'error', op: 'is_not_empty', value: null },
                    { op: 'not', child: { field: 'session_id', op: 'equals', value: '66' } },
                ],
            },
            {
                op: 'and',
                children: [
                    { field: 'input', op: 'contains', value: 'order1234' },
                    { field: 'output', op: 'contains', value: 'Greetings' },
                ],
            },
        ]);
    });

    it('maps every comparison symbol', () => {
        const ops = ['==', '=', '!=', ':', '!:', '>', '<', '>=', '<='].map(
            (symbol) => (parseAuditQuery(`a ${symbol} 1`) as { op: string }).op
        );
        expect(ops).toEqual(['equals', 'equals', 'not_equal', 'contains', 'not_contains', 'gt', 'lt', 'gte', 'lte']);
    });

    it('binds and tighter than or, not tighter than and, and respects parentheses', () => {
        expect(parseAuditQuery('a = 1 or b = 2 and not c = 3')).toEqual({
            op: 'or',
            children: [
                { field: 'a', op: 'equals', value: '1' },
                {
                    op: 'and',
                    children: [
                        { field: 'b', op: 'equals', value: '2' },
                        { op: 'not', child: { field: 'c', op: 'equals', value: '3' } },
                    ],
                },
            ],
        });
        expect(parseAuditQuery('(a = 1 or b = 2) and c = 3')).toEqual({
            op: 'and',
            children: [
                {
                    op: 'or',
                    children: [
                        { field: 'a', op: 'equals', value: '1' },
                        { field: 'b', op: 'equals', value: '2' },
                    ],
                },
                { field: 'c', op: 'equals', value: '3' },
            ],
        });
    });

    it('reads keywords case-insensitively and keeps field casing', () => {
        expect(parseAuditQuery('Error IS NOT EMPTY AND NOT ID == 66')).toEqual({
            op: 'and',
            children: [
                { field: 'Error', op: 'is_not_empty', value: null },
                { op: 'not', child: { field: 'ID', op: 'equals', value: '66' } },
            ],
        });
    });

    it('accepts both bracket styles for in / not in', () => {
        expect(parseAuditQuery('status in (a, "b c")')).toEqual({ field: 'status', op: 'in', value: ['a', 'b c'] });
        expect(parseAuditQuery('status not in [1, 2]')).toEqual({ field: 'status', op: 'not_in', value: ['1', '2'] });
    });

    it('parses is empty', () => {
        expect(parseAuditQuery('error is empty')).toEqual({ field: 'error', op: 'is_empty', value: null });
    });

    it('parses starts with, ends with, exists and not exists', () => {
        expect(parseAuditQuery('name starts with "Sess"')).toEqual({ field: 'name', op: 'starts_with', value: 'Sess' });
        expect(parseAuditQuery('name ENDS WITH Start')).toEqual({ field: 'name', op: 'ends_with', value: 'Start' });
        expect(parseAuditQuery('details.data.x exists')).toEqual({
            field: 'details.data.x',
            op: 'key_exists',
            value: null,
        });
        expect(parseAuditQuery('details.data.x not exists')).toEqual({
            field: 'details.data.x',
            op: 'key_not_exists',
            value: null,
        });
    });

    it('parses text: prefix and bare free text', () => {
        expect(parseAuditQuery('text: "hello world"')).toEqual(text('hello world'));
        expect(parseAuditQuery('TEXT:hello')).toEqual(text('hello'));
        expect(parseAuditQuery('hello and "two words" or 42')).toEqual({
            op: 'or',
            children: [{ op: 'and', children: [text('hello'), text('two words')] }, text('42')],
        });
    });

    it('treats a field literally named text as a field when no colon follows', () => {
        expect(parseAuditQuery('text = a')).toEqual({ field: 'text', op: 'equals', value: 'a' });
    });

    it('keeps values exactly as typed', () => {
        expect(parseAuditQuery('id = 007')).toEqual({ field: 'id', op: 'equals', value: '007' });
        expect(parseAuditQuery('cost >= 1.50')).toEqual({ field: 'cost', op: 'gte', value: '1.50' });
        expect(parseAuditQuery('name = "say \\"hi\\""')).toEqual({ field: 'name', op: 'equals', value: 'say "hi"' });
    });

    it.each([
        '',
        '   ',
        'a = ',
        'a = 1 and',
        '(a = 1',
        'a in (1, 2]',
        'a in 1',
        'a not b',
        'a is full',
        'a starts b',
        'a = 1 b',
        'a = @',
        ')',
    ])('throws a typed error on %j', (query) => {
        expect(() => parseAuditQuery(query)).toThrow(AuditQueryParseError);
    });
});
