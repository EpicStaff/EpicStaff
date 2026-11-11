import { fieldKind } from './field-display';

describe('fieldKind', () => {
    it.each([
        ['an explicit kind wins over the value', 'condition_groups[].next_node', 'uuid:1', null, 'nodeRef'],
        ['an explicit entity kind with null on both sides', 'agent_definition', null, null, 'entityRef'],
        ['an array on either side is a list', 'surface_list', null, [1], 'list'],
        ['an array beats a scalar on the other side', 'unlisted', 'text', ['a'], 'list'],
        ['an object on either side is json', 'input_map', 'broken', { key: 'value' }, 'json'],
        ['a multi-line string on either side is text', 'unlisted', 'short', 'line one\nline two', 'text'],
        ['a long string on either side is text', 'unlisted', 'x'.repeat(81), 'short', 'text'],
        ['a short string is scalar', 'unlisted', 'short', null, 'scalar'],
        ['a number is scalar', 'interval_every', 1, 2, 'scalar'],
    ])('%s', (_case, field, current, version, expected) => {
        expect(fieldKind(field, current, version)).toBe(expected);
        expect(fieldKind(field, version, current)).toBe(expected);
    });
});
