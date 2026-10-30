import {
    AuditConditionGroup,
    AuditConditionJoin,
    AuditFilterOp,
    AuditFilterState,
    createAuditCondition,
    EMPTY_AUDIT_FILTER,
} from '../models/audit-filter.models';
import { SESSION_FIELD_CATALOG } from '../models/audit-filter-options';
import { USER_ACTION_FIELD_CATALOG } from '../models/audit-user-action-filter-options';
import { compileAuditFilter } from './compile-audit-filter.util';
import { clearAuditFilterField, describeAuditFilter } from './describe-audit-filter.util';

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

    it('marks operators and joins as keywords but never the user value', () => {
        const chips = describeAuditFilter({ ...EMPTY_AUDIT_FILTER, input: [group('and', 'equals', 'b')] });
        const keywords = chips
            .find((chip) => chip.key === 'input')
            ?.parts?.filter((part) => part.isKeyword)
            .map((part) => part.text);
        expect(keywords).toEqual(['contains', 'AND', 'contains']);
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
        expect(chips.map(({ key, label, value }) => ({ key, label, value }))).toEqual([
            { key: 'query', label: 'Query', value: 'name == "Session Start"' },
        ]);
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

describe('sessions filter compatibility', () => {
    const condition = (op: AuditFilterOp, value: string, key = '') => ({ ...createAuditCondition(), key, op, value });
    const sessionState: AuditFilterState = {
        ...EMPTY_AUDIT_FILTER,
        searchText: ' boom ',
        matchScope: { children: true, rowsBeforeEnabled: true, rowsBefore: 3, fullSessionHistory: false },
        kinds: ['event'],
        flow: { op: 'not_in', values: ['Billing'] },
        agent: { op: 'in', values: ['7'] },
        tool: { op: 'not_in', values: ['serper', 'scrape'] },
        id: { mode: 'range', from: '10', to: '20', value: '', values: [] },
        statuses: ['failed'],
        dateFrom: '2026-01-01T00:00:00.000Z',
        dateTo: '2026-02-01T00:00:00.000Z',
        nodeTypes: ['AGENT', 'PYTHON'],
        tokens: { op: 'gt', value: '100' },
        error: [{ id: 'error', join: 'or', conditions: [condition('is_not_empty', '')] }],
        input: [{ id: 'input', join: 'or', conditions: [condition('equals', 'x', 'order.id')] }],
        task: [{ id: 'task', join: 'or', conditions: [condition('contains', 'invoice')] }],
    };
    // captured from the sessions page before the user actions tab existed; key order included
    const compiledBefore =
        '{"filters":{"op":"and","children":[{"field":"__text__","op":"contains","value":"boom"},' +
        '{"field":"kind","op":"in","value":["event"]},{"field":"flow_name","op":"not_in","value":["Billing"]},' +
        '{"field":"agent","op":"in","value":[7]},{"op":"not","child":{"op":"or","children":[' +
        '{"field":"details.data.name","op":"equals","value":"serper"},' +
        '{"field":"details.data.name","op":"equals","value":"scrape"}]}},' +
        '{"field":"session_id","op":"gte","value":10},{"field":"session_id","op":"lte","value":20},' +
        '{"field":"status","op":"in","value":["failed"]},' +
        '{"field":"event_time","op":"gte","value":"2026-01-01T00:00:00.000Z"},' +
        '{"field":"event_time","op":"lte","value":"2026-02-01T00:00:00.000Z"},' +
        '{"field":"node_type","op":"in","value":["AGENT","PYTHON"]},' +
        '{"field":"details.data.token_usage.total_tokens","op":"gt","value":100},' +
        '{"field":"error","op":"is_not_empty","value":null},' +
        '{"field":"input.order.id","op":"equals","value":"x"},' +
        '{"field":"task","op":"contains","value":"invoice"}]},' +
        '"matchScope":{"ancestors":true,"children":true,"rows_before":3}}';

    it.each([
        ['the sessions page', undefined],
        ['the sessions filter panel', SESSION_FIELD_CATALOG],
    ])('sessions filter panel compiles the same filter as before (%s)', (_caller, catalog) => {
        expect(JSON.stringify(compileAuditFilter(sessionState, catalog))).toBe(compiledBefore);
    });
});

describe('user actions filter', () => {
    const conditions = (op: AuditFilterOp, value: string): AuditConditionGroup[] => [
        { id: 'group', join: 'or', conditions: [{ ...createAuditCondition(), op, value }] },
    ];

    it('compiles the catalog fields in catalog order, then the date, with no match scope', () => {
        const result = compileAuditFilter(
            {
                ...EMPTY_AUDIT_FILTER,
                searchText: 'ann',
                dateFrom: '2026-01-01T00:00:00.000Z',
                textConditions: { target_name: conditions('starts_with', 'Bill') },
                selections: { action: { op: 'not_in', values: ['signed_in', 'signed_out'] } },
            },
            USER_ACTION_FIELD_CATALOG
        );

        expect(result).toEqual({
            filters: {
                op: 'and',
                children: [
                    { field: '__text__', op: 'contains', value: 'ann' },
                    { field: 'action', op: 'not_in', value: ['signed_in', 'signed_out'] },
                    { field: 'target_name', op: 'starts_with', value: 'Bill' },
                    { field: 'event_time', op: 'gte', value: '2026-01-01T00:00:00.000Z' },
                ],
            },
        });
    });

    it('never sends a session filter left in the state', () => {
        const result = compileAuditFilter(
            { ...EMPTY_AUDIT_FILTER, kinds: ['event'], statuses: ['failed'] },
            USER_ACTION_FIELD_CATALOG
        );

        expect(result).toEqual({});
    });

    it('sends a query without a match scope', () => {
        const result = compileAuditFilter(
            { ...EMPTY_AUDIT_FILTER, mode: 'query', query: 'action = created' },
            USER_ACTION_FIELD_CATALOG
        );

        expect(result).toEqual({ query: 'action = created' });
    });

    it('shows a chip per catalog field, labelled with the option labels', () => {
        const chips = describeAuditFilter(
            {
                ...EMPTY_AUDIT_FILTER,
                selections: { action: { op: 'in', values: ['permanently_deleted'] } },
                textConditions: { actor_email: conditions('contains', 'ann') },
            },
            {},
            USER_ACTION_FIELD_CATALOG
        );

        expect(chips.map(({ key, label, value }) => ({ key, label, value }))).toEqual([
            { key: 'action', label: 'Action', value: 'is any of Permanently deleted' },
            { key: 'actor_email', label: 'Who', value: 'contains ann' },
        ]);
    });

    it('clears one catalog field and keeps the others', () => {
        const state = {
            ...EMPTY_AUDIT_FILTER,
            selections: { action: { op: 'in' as const, values: ['created'] } },
            textConditions: { actor_email: conditions('contains', 'ann') },
        };

        const cleared = clearAuditFilterField(state, 'actor_email');

        expect(compileAuditFilter(cleared, USER_ACTION_FIELD_CATALOG).filters).toEqual({
            field: 'action',
            op: 'in',
            value: ['created'],
        });
    });
});
