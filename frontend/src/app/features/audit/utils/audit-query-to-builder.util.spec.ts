import {
    AuditCondition,
    AuditConditionGroup,
    AuditConditionJoin,
    AuditFilterOp,
    AuditFilterState,
    createAuditCondition,
    DEFAULT_MATCH_SCOPE,
    EMPTY_AUDIT_FILTER,
} from '../models/audit-filter.models';
import { QUERY_EXAMPLES } from '../models/audit-filter-options';
import { auditFilterToQueryText } from './audit-query-text.util';
import { queryToBuilderState } from './audit-query-to-builder.util';
import { compileAuditFilter } from './compile-audit-filter.util';

const current: AuditFilterState = {
    ...EMPTY_AUDIT_FILTER,
    mode: 'query',
    query: 'typed text',
    searchText: 'needle',
    matchScope: { ...DEFAULT_MATCH_SCOPE, children: true },
    kinds: ['session'],
};

function condition(op: AuditFilterOp, value: string, key = '', join: AuditConditionJoin = 'and'): AuditCondition {
    return { ...createAuditCondition(), join, key, op, value };
}

function group(join: AuditConditionJoin, ...conditions: AuditCondition[]): AuditConditionGroup {
    return { id: 'group', join, conditions };
}

function withoutIds(state: AuditFilterState | null): unknown {
    if (state === null) {
        return null;
    }
    const strip = (groups: AuditConditionGroup[]) =>
        groups.map((item) => ({
            join: item.join,
            conditions: item.conditions.map(({ join, key, op, value }) => ({ join, key, op, value })),
        }));
    return {
        ...state,
        error: strip(state.error),
        input: strip(state.input),
        output: strip(state.output),
        details: strip(state.details),
        task: strip(state.task),
        prompt: strip(state.prompt),
        messageText: strip(state.messageText),
    };
}

// what queryToBuilderState should return for a Builder state: the same fields, current's non-Builder fields
function expected(fields: Partial<AuditFilterState>): unknown {
    return withoutIds({
        ...EMPTY_AUDIT_FILTER,
        ...fields,
        query: current.query,
        searchText: current.searchText,
        matchScope: current.matchScope,
    });
}

function toBuilder(query: string): unknown {
    return withoutIds(queryToBuilderState(query, current));
}

describe('queryToBuilderState', () => {
    describe('round trip state -> compile -> query text -> state', () => {
        const cases: [string, Partial<AuditFilterState>][] = [
            ['kinds', { kinds: ['node', 'event'] }],
            ['statuses', { statuses: ['failed'] }],
            ['dates', { dateFrom: '2026-01-01T00:00:00Z', dateTo: '2026-02-01T00:00:00Z' }],
            ['node types', { nodeTypes: ['AGENT', 'PYTHON'] }],
            ['flow in', { flow: { op: 'in', values: ['Flow A', 'Flow B'] } }],
            ['flow not in', { flow: { op: 'not_in', values: ['Flow A'] } }],
            ['id range', { id: { ...EMPTY_AUDIT_FILTER.id, mode: 'range', from: '1', to: '9' } }],
            ['id range lower bound only', { id: { ...EMPTY_AUDIT_FILTER.id, mode: 'range', from: '1' } }],
            ['id range upper bound only', { id: { ...EMPTY_AUDIT_FILTER.id, mode: 'range', to: '9' } }],
            ['id greater than', { id: { ...EMPTY_AUDIT_FILTER.id, mode: 'gt', value: '5' } }],
            ['id less than', { id: { ...EMPTY_AUDIT_FILTER.id, mode: 'lt', value: '5' } }],
            ['id equals', { id: { ...EMPTY_AUDIT_FILTER.id, mode: 'equals', value: '42' } }],
            ['id in', { id: { ...EMPTY_AUDIT_FILTER.id, mode: 'in', values: ['1', '2'] } }],
            ['agent in', { agent: { op: 'in', values: ['3'] } }],
            ['agent not in', { agent: { op: 'not_in', values: ['4', '5'] } }],
            ['one tool', { tool: { op: 'in', values: ['Web_Search_Tool'] } }],
            ['tools in', { tool: { op: 'in', values: ['a', 'b'] } }],
            ['one tool excluded', { tool: { op: 'not_in', values: ['a'] } }],
            ['tools excluded', { tool: { op: 'not_in', values: ['a', 'b'] } }],
            ['tokens greater than', { tokens: { op: 'gt', value: '100' } }],
            ['tokens less than', { tokens: { op: 'lt', value: '100' } }],
            ['tokens equal', { tokens: { op: 'equals', value: '100' } }],
            ['tokens empty', { tokens: { op: 'is_empty', value: '' } }],
            ['error not empty', { error: [group('or', condition('is_not_empty', ''))] }],
            ['error contains', { error: [group('or', condition('contains', 'Timeout'))] }],
            ['input key equals', { input: [group('or', condition('equals', '42', 'order.id'))] }],
            ['input key not equals', { input: [group('or', condition('key_not_equals', '42', 'order.id'))] }],
            ['output key exists', { output: [group('or', condition('key_exists', '', 'result'))] }],
            ['details greater than', { details: [group('or', condition('gt', '3', 'retries'))] }],
            ['task not equal', { task: [group('or', condition('not_equal', 'Write'))] }],
            ['prompt starts with', { prompt: [group('or', condition('starts_with', 'You are'))] }],
            ['message text ends with', { messageText: [group('or', condition('ends_with', 'bye'))] }],
            [
                'one group mixing and/or',
                {
                    input: [
                        group(
                            'or',
                            condition('contains', 'a'),
                            condition('contains', 'b'),
                            condition('contains', 'c', '', 'or')
                        ),
                    ],
                },
            ],
            [
                'groups joined by or',
                {
                    input: [
                        group('or', condition('contains', 'a'), condition('contains', 'b', '', 'or')),
                        group('or', condition('contains', 'c'), condition('contains', 'd')),
                    ],
                },
            ],
            [
                'groups joined by and',
                {
                    input: [
                        group('or', condition('contains', 'a'), condition('contains', 'b', '', 'or')),
                        group('and', condition('contains', 'c')),
                    ],
                },
            ],
            [
                'several fields at once',
                {
                    kinds: ['event'],
                    statuses: ['completed'],
                    flow: { op: 'in', values: ['Flow A'] },
                    agent: { op: 'in', values: ['7'] },
                    tokens: { op: 'gt', value: '10' },
                    input: [group('or', condition('contains', 'order1234'))],
                    messageText: [group('or', condition('contains', 'hi'))],
                },
            ],
        ];

        it.each(cases)('%s', (_name, fields) => {
            const state: AuditFilterState = { ...EMPTY_AUDIT_FILTER, ...fields };
            const filters = compileAuditFilter(state).filters;
            expect(filters).toBeDefined();
            const text = auditFilterToQueryText(filters!);
            expect(toBuilder(text)).toEqual(expected(fields));
        });
    });

    describe('hand-written queries', () => {
        it('clears the Builder for an empty query and keeps the non-Builder fields', () => {
            expect(toBuilder('   ')).toEqual(expected({}));
            expect(queryToBuilderState('', current)?.mode).toBe('builder');
        });

        it.each<[string, Partial<AuditFilterState>]>([
            ['status = "failed"', { statuses: ['failed'] }],
            ['kind == node', { kinds: ['node'] }],
            ['node_type in [AGENT]', { nodeTypes: ['AGENT'] }],
            ['flow_name = "Flow A"', { flow: { op: 'in', values: ['Flow A'] } }],
            ['flow_name != "Flow A"', { flow: { op: 'not_in', values: ['Flow A'] } }],
            ['agent = 3', { agent: { op: 'in', values: ['3'] } }],
            ['agent != 3', { agent: { op: 'not_in', values: ['3'] } }],
            ['tool = Web_Search_Tool', { tool: { op: 'in', values: ['Web_Search_Tool'] } }],
            ['tool != a', { tool: { op: 'not_in', values: ['a'] } }],
            ['tool in (a, b)', { tool: { op: 'in', values: ['a', 'b'] } }],
            ['not tool in (a, b)', { tool: { op: 'not_in', values: ['a', 'b'] } }],
            ['details.data.name = a or details.data.name = b', { tool: { op: 'in', values: ['a', 'b'] } }],
            [
                'session_id >= 1 and session_id <= 5',
                { id: { ...EMPTY_AUDIT_FILTER.id, mode: 'range', from: '1', to: '5' } },
            ],
            [
                'session_id <= 5 and session_id >= 1',
                { id: { ...EMPTY_AUDIT_FILTER.id, mode: 'range', from: '1', to: '5' } },
            ],
            ['event_time >= "2026-01-01"', { dateFrom: '2026-01-01' }],
            ['details.data.token_usage.total_tokens not exists', { tokens: { op: 'is_empty', value: '' } }],
            [
                // a tokens op the Tokens filter lacks stays a Details condition on the same path
                'details.data.token_usage.total_tokens >= 5',
                { details: [group('or', condition('gte', '5', 'data.token_usage.total_tokens'))] },
            ],
            ['input.order.id != 42', { input: [group('or', condition('key_not_equals', '42', 'order.id'))] }],
            [
                'input : a or input : b or input : c',
                {
                    input: [
                        group(
                            'or',
                            condition('contains', 'a'),
                            condition('contains', 'b', '', 'or'),
                            condition('contains', 'c', '', 'or')
                        ),
                    ],
                },
            ],
            [
                // AND binds tighter, so the AND pair becomes its own group
                'input : a or input : b and input : c',
                {
                    input: [
                        group('or', condition('contains', 'a')),
                        group('or', condition('contains', 'b'), condition('contains', 'c')),
                    ],
                },
            ],
            [
                // the multi-group conjunct is moved first so the left fold keeps its meaning
                'input : d and (input : a or input : b and input : c)',
                {
                    input: [
                        group('or', condition('contains', 'a')),
                        group('or', condition('contains', 'b'), condition('contains', 'c')),
                        group('and', condition('contains', 'd')),
                    ],
                },
            ],
            [
                '(kind = event and (status = failed and input : x))',
                { kinds: ['event'], statuses: ['failed'], input: [group('or', condition('contains', 'x'))] },
            ],
        ])('%s', (query, fields) => {
            expect(toBuilder(query)).toEqual(expected(fields));
        });
    });

    describe('keeps values exactly as typed', () => {
        it.each<[string, Partial<AuditFilterState>]>([
            ['input.code = "007"', { input: [group('or', condition('equals', '007', 'code'))] }],
            ['input.code = 007', { input: [group('or', condition('equals', '007', 'code'))] }],
            ['session_id = 007', { id: { ...EMPTY_AUDIT_FILTER.id, mode: 'equals', value: '007' } }],
            ['input : "hello \\"big\\" world"', { input: [group('or', condition('contains', 'hello "big" world'))] }],
            ['prompt starts with "  spaced  "', { prompt: [group('or', condition('starts_with', '  spaced  '))] }],
            ['flow_name in ("My flow", "x, y")', { flow: { op: 'in', values: ['My flow', 'x, y'] } }],
        ])('%s', (query, fields) => {
            expect(toBuilder(query)).toEqual(expected(fields));
        });
    });

    describe('matches field names case-insensitively, like the backend', () => {
        it.each<[string, Partial<AuditFilterState>]>([
            ['STATUS = failed', { statuses: ['failed'] }],
            ['Tool = a', { tool: { op: 'in', values: ['a'] } }],
            ['Session_ID >= 1', { id: { ...EMPTY_AUDIT_FILTER.id, mode: 'range', from: '1' } }],
            // only the root: JSON keys below it are case-sensitive and stay as typed
            ['INPUT.OrderId = x', { input: [group('or', condition('equals', 'x', 'OrderId'))] }],
        ])('%s', (query, fields) => {
            expect(toBuilder(query)).toEqual(expected(fields));
        });
    });

    describe('returns null when the Builder cannot show the query', () => {
        it.each([
            ['OR across fields', 'status = failed or kind = event'],
            ['OR on one select field', 'status = failed or status = completed'],
            ['bare free text', 'hello'],
            ['text: free text', 'text: "hello"'],
            ['free text next to a field', 'kind = event and hello'],
            ['unknown field name', 'name = "Session Start"'],
            ['unknown field duration', 'duration > 5'],
            ['unknown field run_type', 'run_type = x'],
            ['unknown field id', 'id = 5'],
            ['unknown field session_message_id', 'session_message_id = 1'],
            ['invalid status', 'status = running'],
            ['invalid kind in a list', 'kind in (node, bogus)'],
            ['invalid node type', 'node_type = FOO'],
            ['non-numeric agent id', 'agent = abc'],
            ['parse error', 'status in ('],
            ['unclosed parenthesis', '(input : a'],
            ['NOT around a non-tool filter', 'not kind = event'],
            ['double negated tool', 'not tool != a'],
            ['same field twice', 'kind = node and kind = event'],
            ['op the Builder lacks for a select field', 'kind not in (node)'],
            ['op the Builder lacks for dates', 'event_time > "2026-01-01"'],
            ['op the error filter lacks', 'error = x'],
            ['key on a keyless field', 'task.name : x'],
            ['id equals plus a range bound', 'session_id = 3 and session_id >= 1'],
            ['non-numeric id', 'session_id = abc'],
            [
                'precedence the Builder cannot fold',
                '(input : a or input : b and input : c) and (input : d or input : e and input : f)',
            ],
            ['nesting deeper than groups', 'input : a or (input : b and (input : c or input : d))'],
            ['empty value the Builder would drop', 'input : ""'],
            ['agent together with tool', 'agent = 1 and tool = a'],
            ['field unavailable for the chosen kind', 'kind = session and status = failed'],
        ])('%s', (_name, query) => {
            expect(queryToBuilderState(query, current)).toBeNull();
        });
    });

    it('maps the first and last query examples; the middle two need the query tab', () => {
        // 2: unknown field name, 3: NOT around session_id
        expect(QUERY_EXAMPLES.map((query) => toBuilder(query))).toEqual([
            expected({ statuses: ['failed'], nodeTypes: ['AGENT', 'PYTHON'] }),
            null,
            null,
            expected({
                input: [group('or', condition('contains', 'order1234'))],
                output: [group('or', condition('contains', 'Greetings'))],
            }),
        ]);
    });
});
