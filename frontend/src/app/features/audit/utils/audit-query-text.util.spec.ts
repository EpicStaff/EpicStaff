import {
    AuditConditionGroup,
    AuditFilterNode,
    AuditFilterOp,
    AuditFilterState,
    createAuditCondition,
    EMPTY_AUDIT_FILTER,
} from '../models/audit-filter.models';
import { parseAuditQuery } from './audit-query-language.util';
import { auditFilterToQueryText } from './audit-query-text.util';
import { compileAuditFilter } from './compile-audit-filter.util';

const leaf = (field: string, op: AuditFilterOp, value: unknown): AuditFilterNode => ({ field, op, value });

// the parser keeps values as typed text, so compiled numbers come back as strings
function normalizeNumbers(node: AuditFilterNode): AuditFilterNode {
    if ('children' in node) {
        return { op: node.op, children: node.children.map(normalizeNumbers) };
    }
    if (node.op === 'not') {
        return { op: 'not', child: normalizeNumbers(node.child) };
    }
    const toText = (value: unknown) => (typeof value === 'number' ? String(value) : value);
    return { ...node, value: Array.isArray(node.value) ? node.value.map(toText) : toText(node.value) };
}

describe('auditFilterToQueryText', () => {
    it.each<[AuditFilterOp, unknown, string]>([
        ['equals', 'a', 'f = "a"'],
        ['not_equal', 'a', 'f != "a"'],
        ['key_not_equals', 'a', 'f != "a"'],
        ['contains', 'a', 'f : "a"'],
        ['not_contains', 'a', 'f !: "a"'],
        ['gt', 5, 'f > 5'],
        ['lt', 5, 'f < 5'],
        ['gte', 1.5, 'f >= 1.5'],
        ['lte', '2024-01-01', 'f <= "2024-01-01"'],
        ['in', ['a', 1], 'f in ("a", 1)'],
        ['not_in', ['a'], 'f not in ("a")'],
        ['is_empty', null, 'f is empty'],
        ['is_not_empty', null, 'f is not empty'],
        ['key_exists', null, 'f exists'],
        ['key_not_exists', null, 'f not exists'],
        ['starts_with', 'a', 'f starts with "a"'],
        ['ends_with', 'a', 'f ends with "a"'],
    ])('writes %s', (op, value, expected) => {
        expect(auditFilterToQueryText(leaf('f', op, value))).toBe(expected);
    });

    it('writes free text with the text: prefix and escapes quotes', () => {
        expect(auditFilterToQueryText(leaf('__text__', 'contains', 'say "hi"'))).toBe('text: "say \\"hi\\""');
    });

    it('parenthesizes nested groups but not the top level', () => {
        const node: AuditFilterNode = {
            op: 'and',
            children: [
                { op: 'or', children: [leaf('a', 'equals', 1), leaf('b', 'equals', 2)] },
                { op: 'not', child: { op: 'and', children: [leaf('c', 'is_empty', null), leaf('d', 'gt', 3)] } },
                { op: 'not', child: leaf('e', 'equals', 'x') },
            ],
        };
        expect(auditFilterToQueryText(node)).toBe('(a = 1 or b = 2) and not (c is empty and d > 3) and not e = "x"');
    });

    it('throws on an op with no text form or a value it cannot write', () => {
        expect(() => auditFilterToQueryText(leaf('f', 'regex' as AuditFilterOp, 'a'))).toThrow();
        expect(() => auditFilterToQueryText(leaf('f', 'equals', null))).toThrow();
        expect(() => auditFilterToQueryText(leaf('f', 'in', 'a'))).toThrow();
    });
});

describe('Builder state round-trip through query text', () => {
    function conditions(...items: [string, AuditFilterOp, string][]): AuditConditionGroup[] {
        return [
            {
                id: 'group',
                join: 'or',
                conditions: items.map(([key, op, value], index) => ({
                    ...createAuditCondition(),
                    join: index === 2 ? 'or' : 'and',
                    key,
                    op,
                    value,
                })),
            },
        ];
    }

    const states: [string, Partial<AuditFilterState>][] = [
        ['search text only', { searchText: 'say "hi"' }],
        [
            'enums, flows, agents and tools',
            {
                kinds: ['node', 'event'],
                statuses: ['failed'],
                nodeTypes: ['AGENT'],
                flow: { op: 'not_in', values: ['Flow A', 'Flow B'] },
                agent: { op: 'in', values: ['3', '7'] },
                tool: { op: 'not_in', values: ['Web_Search_Tool', 'Notification_Tool'] },
            },
        ],
        [
            'ids, dates and tokens',
            {
                id: { mode: 'range', from: '10', to: '20', value: '', values: [] },
                dateFrom: '2024-01-01T00:00:00Z',
                tokens: { op: 'gte', value: '1500' },
            },
        ],
        ['missing tokens', { tokens: { op: 'is_empty', value: '' } }],
        [
            'condition groups with every value-free and new op',
            {
                error: conditions(['', 'is_not_empty', ''], ['code', 'starts_with', 'E0'], ['trace', 'key_exists', '']),
                details: conditions(['data.name', 'ends_with', '_tool'], ['data.x', 'key_not_exists', '']),
                input: conditions(['', 'not_contains', '007']),
            },
        ],
    ];

    it.each(states)('preserves %s', (_label, overrides) => {
        const { filters } = compileAuditFilter({ ...EMPTY_AUDIT_FILTER, ...overrides });
        if (filters === undefined) {
            throw new Error('state compiled to no filter');
        }
        expect(parseAuditQuery(auditFilterToQueryText(filters))).toEqual(normalizeNumbers(filters));
    });
});
