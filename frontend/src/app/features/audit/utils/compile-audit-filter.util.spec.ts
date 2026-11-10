import {
    AuditConditionGroup,
    AuditConditionJoin,
    AuditFilterNode,
    AuditFilterOp,
    AuditFilterState,
    AuditIdFilter,
    createAuditCondition,
    EMPTY_AUDIT_FILTER,
} from '../models/audit-filter.models';
import { SESSION_FIELD_CATALOG } from '../models/audit-filter-options';
import { USER_ACTION_FIELD_CATALOG } from '../models/audit-user-action-filter-options';
import { compileAuditFilter } from './compile-audit-filter.util';
import { clearAuditFilterField, describeAuditFilter } from './describe-audit-filter.util';

function group(join: AuditConditionJoin, ...values: string[]): AuditConditionGroup {
    return {
        id: values.join('-'),
        join,
        conditions: values.map((value) => ({ ...createAuditCondition(['contains']), value })),
    };
}

const leaf = (value: string) => ({ field: 'input', op: 'contains', value });

describe('audit condition groups', () => {
    it('compiles a single group exactly like the old flat list', () => {
        const { filters } = compileAuditFilter(
            { ...EMPTY_AUDIT_FILTER, input: [group('or', 'a', 'b')] },
            SESSION_FIELD_CATALOG
        );
        expect(filters).toEqual({ op: 'and', children: [leaf('a'), leaf('b')] });
    });

    it('joins groups by the group join and ignores the first group join', () => {
        const { filters } = compileAuditFilter(
            {
                ...EMPTY_AUDIT_FILTER,
                input: [group('and', 'a', 'b'), group('or', 'c')],
            },
            SESSION_FIELD_CATALOG
        );
        expect(filters).toEqual({
            op: 'or',
            children: [{ op: 'and', children: [leaf('a'), leaf('b')] }, leaf('c')],
        });
    });

    it('skips a group with no usable condition', () => {
        const { filters } = compileAuditFilter(
            { ...EMPTY_AUDIT_FILTER, input: [group('and', ''), group('or', 'c')] },
            SESSION_FIELD_CATALOG
        );
        expect(filters).toEqual(leaf('c'));
    });

    it('brackets compound groups in the chip', () => {
        const chips = describeAuditFilter(
            { ...EMPTY_AUDIT_FILTER, input: [group('and', 'a', 'b'), group('or', 'c')] },
            SESSION_FIELD_CATALOG
        );
        expect(chips.find((chip) => chip.key === 'input')?.value).toBe('(contains a AND contains b) OR contains c');
    });

    it('marks operators and joins as keywords but never the user value', () => {
        const chips = describeAuditFilter(
            { ...EMPTY_AUDIT_FILTER, input: [group('and', 'equals', 'b')] },
            SESSION_FIELD_CATALOG
        );
        const keywords = chips
            .find((chip) => chip.key === 'input')
            ?.parts?.filter((part) => part.isKeyword)
            .map((part) => part.text);
        expect(keywords).toEqual(['contains', 'AND', 'contains']);
    });

    it('folds three groups left to right in both the chip and the compiled tree', () => {
        const state = { ...EMPTY_AUDIT_FILTER, input: [group('and', 'a', 'b'), group('or', 'c'), group('and', 'd')] };
        const chips = describeAuditFilter(state, SESSION_FIELD_CATALOG);
        expect(chips.find((chip) => chip.key === 'input')?.value).toBe(
            '((contains a AND contains b) OR contains c) AND contains d'
        );
        expect(compileAuditFilter(state, SESSION_FIELD_CATALOG).filters).toEqual({
            op: 'and',
            children: [{ op: 'or', children: [{ op: 'and', children: [leaf('a'), leaf('b')] }, leaf('c')] }, leaf('d')],
        });
    });
});

describe('audit query mode', () => {
    it('sends the trimmed query instead of the builder filters', () => {
        const result = compileAuditFilter(
            {
                ...EMPTY_AUDIT_FILTER,
                mode: 'query',
                query: '  status in ["failed"]  ',
                input: [group('and', 'ignored')],
            },
            SESSION_FIELD_CATALOG
        );
        expect(result.filters).toBeUndefined();
        expect(result.query).toBe('status in ["failed"]');
    });

    it('sends neither filters nor query for an empty query', () => {
        const result = compileAuditFilter(
            { ...EMPTY_AUDIT_FILTER, mode: 'query', query: '   ' },
            SESSION_FIELD_CATALOG
        );
        expect(result.filters).toBeUndefined();
        expect(result.query).toBeUndefined();
    });

    it('shows a single query chip', () => {
        const chips = describeAuditFilter(
            {
                ...EMPTY_AUDIT_FILTER,
                mode: 'query',
                query: 'name == "Session Start"',
                input: [group('and', 'ignored')],
            },
            SESSION_FIELD_CATALOG
        );
        expect(chips.map(({ key, label, value }) => ({ key, label, value }))).toEqual([
            { key: 'query', label: 'Query', value: 'name == "Session Start"' },
        ]);
    });
});

describe('audit free-text search', () => {
    const textLeaf = (value: string) => ({ field: '__text__', op: 'contains', value });

    it('ANDs the trimmed text leaf with the other builder filters', () => {
        const { filters } = compileAuditFilter(
            { ...EMPTY_AUDIT_FILTER, searchText: '  boom ', kinds: ['event'] },
            SESSION_FIELD_CATALOG
        );
        expect(filters).toEqual({
            op: 'and',
            children: [textLeaf('boom'), { field: 'kind', op: 'in', value: ['event'] }],
        });
    });

    it('wraps the query and appends the text clause in query mode', () => {
        const { query, filters } = compileAuditFilter(
            {
                ...EMPTY_AUDIT_FILTER,
                mode: 'query',
                query: 'status in ["failed"]',
                searchText: 'boom',
            },
            SESSION_FIELD_CATALOG
        );
        expect(filters).toBeUndefined();
        expect(query).toBe('(status in ["failed"]) and text: "boom"');
    });

    it('sends only the text clause when the query is empty', () => {
        const { query } = compileAuditFilter(
            { ...EMPTY_AUDIT_FILTER, mode: 'query', query: ' ', searchText: 'boom' },
            SESSION_FIELD_CATALOG
        );
        expect(query).toBe('text: "boom"');
    });

    it('escapes double quotes in the text clause', () => {
        const { query } = compileAuditFilter(
            { ...EMPTY_AUDIT_FILTER, mode: 'query', searchText: 'say "hi"' },
            SESSION_FIELD_CATALOG
        );
        expect(query).toBe('text: "say \\"hi\\""');
    });

    it('ignores whitespace-only text in both modes', () => {
        expect(
            compileAuditFilter({ ...EMPTY_AUDIT_FILTER, searchText: '   ' }, SESSION_FIELD_CATALOG).filters
        ).toBeUndefined();
        expect(
            compileAuditFilter({ ...EMPTY_AUDIT_FILTER, mode: 'query', searchText: '   ' }, SESSION_FIELD_CATALOG).query
        ).toBeUndefined();
        expect(describeAuditFilter({ ...EMPTY_AUDIT_FILTER, searchText: '   ' }, SESSION_FIELD_CATALOG)).toEqual([]);
    });

    it('shows the search chip in both modes', () => {
        const chip = { key: 'search', label: 'Search', value: 'boom' };
        expect(
            describeAuditFilter({ ...EMPTY_AUDIT_FILTER, searchText: ' boom ' }, SESSION_FIELD_CATALOG)
        ).toContainEqual(chip);
        expect(
            describeAuditFilter(
                { ...EMPTY_AUDIT_FILTER, mode: 'query', query: 'x == 1', searchText: 'boom' },
                SESSION_FIELD_CATALOG
            )
        ).toContainEqual(chip);
    });
});

describe('sessions filter compatibility', () => {
    const condition = (op: AuditFilterOp, value: string, key = '') => ({ ...createAuditCondition([op]), key, value });
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

    it('sessions filter panel compiles the same filter as before', () => {
        expect(compileAuditFilter(sessionState, SESSION_FIELD_CATALOG)).toEqual(JSON.parse(compiledBefore));
    });
});

describe('user actions filter', () => {
    const conditions = (op: AuditFilterOp, value: string): AuditConditionGroup[] => [
        { id: 'group', join: 'or', conditions: [{ ...createAuditCondition([op]), value }] },
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

    it.each([
        [
            'in',
            {
                op: 'or',
                children: [
                    {
                        op: 'and',
                        children: [
                            { field: 'target_type', op: 'equals', value: 'flow' },
                            { field: 'target_id', op: 'in', value: ['12', '15'] },
                        ],
                    },
                    {
                        op: 'and',
                        children: [
                            { field: 'parent_type', op: 'equals', value: 'flow' },
                            { field: 'parent_id', op: 'in', value: ['12', '15'] },
                        ],
                    },
                ],
            },
        ],
        [
            'not_in',
            {
                op: 'not',
                child: {
                    op: 'or',
                    children: [
                        {
                            op: 'and',
                            children: [
                                { field: 'target_type', op: 'equals', value: 'flow' },
                                { field: 'target_id', op: 'in', value: ['12', '15'] },
                            ],
                        },
                        {
                            op: 'and',
                            children: [
                                { field: 'parent_type', op: 'equals', value: 'flow' },
                                { field: 'parent_id', op: 'in', value: ['12', '15'] },
                            ],
                        },
                    ],
                },
            },
        ],
    ] as const)('compiles Flow %s to the flows themselves and everything inside them, by id', (op, expected) => {
        const result = compileAuditFilter(
            { ...EMPTY_AUDIT_FILTER, selections: { flow_id: { op, values: ['12', '15'] } } },
            USER_ACTION_FIELD_CATALOG
        );

        expect(result).toEqual({ filters: expected });
    });

    it.each(['in', 'not_in'] as const)('compiles User %s to the numeric actor user ids', (op) => {
        const result = compileAuditFilter(
            { ...EMPTY_AUDIT_FILTER, selections: { actor_user_id: { op, values: ['3', '41'] } } },
            USER_ACTION_FIELD_CATALOG
        );

        expect(result).toEqual({ filters: { field: 'actor_user_id', op, value: [3, 41] } });
    });

    it.each(['in', 'not_in'] as const)('compiles Target Type %s to the raw recorded types', (op) => {
        const result = compileAuditFilter(
            { ...EMPTY_AUDIT_FILTER, selections: { target_type: { op, values: ['flow', 'python code node'] } } },
            USER_ACTION_FIELD_CATALOG
        );

        expect(result).toEqual({ filters: { field: 'target_type', op, value: ['flow', 'python code node'] } });
    });

    it('shows a chip per catalog field, naming the picked flows, members and target types', () => {
        const chips = describeAuditFilter(
            {
                ...EMPTY_AUDIT_FILTER,
                selections: {
                    action: { op: 'in', values: ['moved_to_recycle_bin'] },
                    actor_user_id: { op: 'in', values: ['3'] },
                    target_type: { op: 'in', values: ['python code node', 'webhook trigger'] },
                    flow_id: { op: 'not_in', values: ['12', '99'] },
                },
                textConditions: { target_name: conditions('contains', 'Inv') },
            },
            USER_ACTION_FIELD_CATALOG,
            {
                members: [{ value: '3', label: 'Ann Lee (ann@example.com)' }],
                flows: [{ value: '12', label: 'Billing' }],
                targetTypes: [{ value: 'python code node', label: 'Python code node' }],
            }
        );

        expect(chips.map(({ key, label, value }) => ({ key, label, value }))).toEqual([
            { key: 'action', label: 'Action', value: 'is any of Moved to Recycle Bin' },
            { key: 'actor_user_id', label: 'User', value: 'is any of Ann Lee (ann@example.com)' },
            // a type not in the loaded list shows as recorded
            { key: 'target_type', label: 'Target Type', value: 'is any of Python code node, webhook trigger' },
            // a flow no longer in the list shows its id
            { key: 'flow_id', label: 'Flow', value: 'is none of Billing, 99' },
            { key: 'target_name', label: 'Target Name', value: 'contains Inv' },
        ]);
    });

    it.each(['flow_id', 'actor_user_id', 'target_type'])('clears the %s picker and keeps the other fields', (field) => {
        const state: AuditFilterState = {
            ...EMPTY_AUDIT_FILTER,
            selections: { action: { op: 'in', values: ['created'] }, [field]: { op: 'in', values: ['5'] } },
        };

        const cleared = clearAuditFilterField(state, field);

        expect(compileAuditFilter(cleared, USER_ACTION_FIELD_CATALOG).filters).toEqual({
            field: 'action',
            op: 'in',
            value: ['created'],
        });
    });
});

describe('ID filter', () => {
    const idFilter = (change: Partial<AuditIdFilter>): AuditIdFilter => ({ ...EMPTY_AUDIT_FILTER.id, ...change });
    // each mode compiled onto `field`, as the Sessions tab always compiled it onto session_id
    const modes = (field: string): [string, AuditIdFilter, AuditFilterNode | undefined][] => [
        [
            'range',
            idFilter({ mode: 'range', from: '5', to: '9' }),
            {
                op: 'and',
                children: [
                    { field, op: 'gte', value: 5 },
                    { field, op: 'lte', value: 9 },
                ],
            },
        ],
        ['range from only', idFilter({ mode: 'range', from: '5' }), { field, op: 'gte', value: 5 }],
        ['range to only', idFilter({ mode: 'range', to: '9' }), { field, op: 'lte', value: 9 }],
        ['more than', idFilter({ mode: 'gt', value: '5' }), { field, op: 'gt', value: 5 }],
        ['less than', idFilter({ mode: 'lt', value: '5' }), { field, op: 'lt', value: 5 }],
        ['exact', idFilter({ mode: 'equals', value: '5' }), { field, op: 'equals', value: 5 }],
        ['specific', idFilter({ mode: 'in', values: ['4', '7'] }), { field, op: 'in', value: [4, 7] }],
        ['empty', idFilter({ mode: 'gt' }), undefined],
    ];

    it.each(modes('session_id'))('compiles Sessions %s onto session_id', (_mode, id, expected) => {
        expect(compileAuditFilter({ ...EMPTY_AUDIT_FILTER, id }, SESSION_FIELD_CATALOG).filters).toEqual(expected);
    });

    it.each(modes('number'))('compiles User actions %s onto number', (_mode, id, expected) => {
        const state: AuditFilterState = { ...EMPTY_AUDIT_FILTER, idFilters: { number: id } };

        expect(compileAuditFilter(state, USER_ACTION_FIELD_CATALOG).filters).toEqual(expected);
    });

    it('never sends the Sessions ID filter left in a user actions state', () => {
        const result = compileAuditFilter(
            { ...EMPTY_AUDIT_FILTER, id: idFilter({ mode: 'equals', value: '5' }) },
            USER_ACTION_FIELD_CATALOG
        );

        expect(result).toEqual({});
    });

    it.each<[AuditIdFilter, string]>([
        [idFilter({ mode: 'range', from: '5', to: '9' }), '5 — 9'],
        [idFilter({ mode: 'range', from: '5' }), 'from 5'],
        [idFilter({ mode: 'range', to: '9' }), 'until 9'],
        [idFilter({ mode: 'gt', value: '5' }), 'more than 5'],
        [idFilter({ mode: 'lt', value: '5' }), 'less than 5'],
        [idFilter({ mode: 'equals', value: '5' }), '5'],
        [idFilter({ mode: 'in', values: ['4', '7'] }), '4, 7'],
    ])('shows the user actions ID chip first, worded like the Sessions one (%o)', (id, value) => {
        const chips = describeAuditFilter(
            {
                ...EMPTY_AUDIT_FILTER,
                idFilters: { number: id },
                selections: { action: { op: 'in', values: ['created'] } },
            },
            USER_ACTION_FIELD_CATALOG
        );

        expect(chips.map(({ key, label, value }) => ({ key, label, value }))).toEqual([
            { key: 'number', label: 'ID', value },
            { key: 'action', label: 'Action', value: 'is any of Created' },
        ]);
    });

    it('clears the user actions ID chip and keeps the other fields', () => {
        const state: AuditFilterState = {
            ...EMPTY_AUDIT_FILTER,
            idFilters: { number: idFilter({ mode: 'gt', value: '5' }) },
            selections: { action: { op: 'in', values: ['created'] } },
        };

        const cleared = clearAuditFilterField(state, 'number');

        expect(describeAuditFilter(cleared, USER_ACTION_FIELD_CATALOG).map((chip) => chip.key)).toEqual(['action']);
        expect(compileAuditFilter(cleared, USER_ACTION_FIELD_CATALOG).filters).toEqual({
            field: 'action',
            op: 'in',
            value: ['created'],
        });
    });
});
