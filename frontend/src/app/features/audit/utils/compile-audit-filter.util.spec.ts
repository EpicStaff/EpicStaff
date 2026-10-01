import {
    AuditConditionGroup,
    AuditConditionJoin,
    createAuditCondition,
    EMPTY_AUDIT_FILTER,
} from '../models/audit-filter.models';
import { compileAuditFilter } from './compile-audit-filter.util';
import { describeAuditFilter } from './describe-audit-filter.util';

function group(join: AuditConditionJoin, ...values: string[]): AuditConditionGroup {
    return { id: values.join('-'), join, conditions: values.map((value) => ({ ...createAuditCondition(), value })) };
}

const leaf = (value: string) => ({ field: 'input', op: 'contains', value });

describe('audit condition groups', () => {
    it('compiles a single group exactly like the old flat list', () => {
        const { filters } = compileAuditFilter({ ...EMPTY_AUDIT_FILTER, input: [group('or', 'a', 'b')] });
        expect(filters).toEqual({ op: 'and', children: [leaf('a'), leaf('b')] });
    });

    it('joins groups by the group join and ignores the first group join', () => {
        const { filters } = compileAuditFilter({
            ...EMPTY_AUDIT_FILTER,
            input: [group('and', 'a', 'b'), group('or', 'c')],
        });
        expect(filters).toEqual({
            op: 'or',
            children: [{ op: 'and', children: [leaf('a'), leaf('b')] }, leaf('c')],
        });
    });

    it('skips a group with no usable condition', () => {
        const { filters } = compileAuditFilter({ ...EMPTY_AUDIT_FILTER, input: [group('and', ''), group('or', 'c')] });
        expect(filters).toEqual(leaf('c'));
    });

    it('brackets compound groups in the chip', () => {
        const chips = describeAuditFilter({ ...EMPTY_AUDIT_FILTER, input: [group('and', 'a', 'b'), group('or', 'c')] });
        expect(chips.find((chip) => chip.key === 'input')?.value).toBe('(contains a AND contains b) OR contains c');
    });

    it('folds three groups left to right in both the chip and the compiled tree', () => {
        const state = { ...EMPTY_AUDIT_FILTER, input: [group('and', 'a', 'b'), group('or', 'c'), group('and', 'd')] };
        const chips = describeAuditFilter(state);
        expect(chips.find((chip) => chip.key === 'input')?.value).toBe(
            '((contains a AND contains b) OR contains c) AND contains d'
        );
        expect(compileAuditFilter(state).filters).toEqual({
            op: 'and',
            children: [{ op: 'or', children: [{ op: 'and', children: [leaf('a'), leaf('b')] }, leaf('c')] }, leaf('d')],
        });
    });
});

describe('audit query mode', () => {
    it('sends the trimmed query instead of the builder filters', () => {
        const result = compileAuditFilter({
            ...EMPTY_AUDIT_FILTER,
            mode: 'query',
            query: '  status in ["failed"]  ',
            input: [group('and', 'ignored')],
        });
        expect(result.filters).toBeUndefined();
        expect(result.query).toBe('status in ["failed"]');
    });

    it('sends neither filters nor query for an empty query', () => {
        const result = compileAuditFilter({ ...EMPTY_AUDIT_FILTER, mode: 'query', query: '   ' });
        expect(result.filters).toBeUndefined();
        expect(result.query).toBeUndefined();
    });

    it('shows a single query chip', () => {
        const chips = describeAuditFilter({
            ...EMPTY_AUDIT_FILTER,
            mode: 'query',
            query: 'name == "Session Start"',
            input: [group('and', 'ignored')],
        });
        expect(chips).toEqual([{ key: 'query', label: 'Query', value: 'name == "Session Start"' }]);
    });
});

describe('audit free-text search', () => {
    const textLeaf = (value: string) => ({ field: '__text__', op: 'contains', value });

    it('ANDs the trimmed text leaf with the other builder filters', () => {
        const { filters } = compileAuditFilter({ ...EMPTY_AUDIT_FILTER, searchText: '  boom ', kinds: ['event'] });
        expect(filters).toEqual({
            op: 'and',
            children: [textLeaf('boom'), { field: 'kind', op: 'in', value: ['event'] }],
        });
    });

    it('wraps the query and appends the text clause in query mode', () => {
        const { query, filters } = compileAuditFilter({
            ...EMPTY_AUDIT_FILTER,
            mode: 'query',
            query: 'status in ["failed"]',
            searchText: 'boom',
        });
        expect(filters).toBeUndefined();
        expect(query).toBe('(status in ["failed"]) and text: "boom"');
    });

    it('sends only the text clause when the query is empty', () => {
        const { query } = compileAuditFilter({ ...EMPTY_AUDIT_FILTER, mode: 'query', query: ' ', searchText: 'boom' });
        expect(query).toBe('text: "boom"');
    });

    it('escapes double quotes in the text clause', () => {
        const { query } = compileAuditFilter({ ...EMPTY_AUDIT_FILTER, mode: 'query', searchText: 'say "hi"' });
        expect(query).toBe('text: "say \\"hi\\""');
    });

    it('ignores whitespace-only text in both modes', () => {
        expect(compileAuditFilter({ ...EMPTY_AUDIT_FILTER, searchText: '   ' }).filters).toBeUndefined();
        expect(compileAuditFilter({ ...EMPTY_AUDIT_FILTER, mode: 'query', searchText: '   ' }).query).toBeUndefined();
        expect(describeAuditFilter({ ...EMPTY_AUDIT_FILTER, searchText: '   ' })).toEqual([]);
    });

    it('shows the search chip in both modes', () => {
        const chip = { key: 'search', label: 'Search', value: 'boom' };
        expect(describeAuditFilter({ ...EMPTY_AUDIT_FILTER, searchText: ' boom ' })).toContainEqual(chip);
        expect(
            describeAuditFilter({ ...EMPTY_AUDIT_FILTER, mode: 'query', query: 'x == 1', searchText: 'boom' })
        ).toContainEqual(chip);
    });
});
