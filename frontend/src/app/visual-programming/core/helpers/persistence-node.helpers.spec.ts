import {
    existenceBadge,
    extractPlaceholders,
    isMalformedKey,
    isSameLookupRequest,
    isStatePath,
    isStaticKey,
    keyTemplateHint,
    nonStatePathPlaceholders,
    normalizeEntry,
    parseDefaultValue,
    reshapeEntriesForMode,
    STATE_PATH,
} from './persistence-node.helpers';

describe('persistence node helpers', () => {
    it('extracts placeholders', () => {
        expect(extractPlaceholders('profile_{variables.user.id}_{variables.region}')).toEqual([
            'variables.user.id',
            'variables.region',
        ]);
        expect(extractPlaceholders('static')).toEqual([]);
    });

    it('detects static keys', () => {
        expect(isStaticKey('config')).toBe(true);
        expect(isStaticKey('profile_{variables.user.id}')).toBe(false);
        expect(isStaticKey('profile_{user_id}')).toBe(false);
        expect(isStaticKey('profile_{}')).toBe(false);
        expect(isStaticKey('profile_{variables.id')).toBe(false);
    });

    it('detects malformed keys the way crew does', () => {
        for (const key of ['p_{}', 'p_{variables.id', 'p_variables.id}', 'p_{{variables.id}}']) {
            expect(isMalformedKey(key)).toBe(true);
        }
        for (const key of ['static', 'p_{variables.id}', 'p_{user_id}_{variables[0]}']) {
            expect(isMalformedKey(key)).toBe(false);
        }
    });

    it('recognises state paths', () => {
        for (const path of ['variables.a.b', 'variables.x|0', 'variables[0]']) {
            expect(STATE_PATH.test(path)).toBe(true);
        }
        for (const path of ['name', 'variables', 'variables.', 'variables[', 'variablesX.a', 'state.variables.a']) {
            expect(STATE_PATH.test(path)).toBe(false);
        }
        expect(isStatePath('  variables.a  ')).toBe(true);
        expect(isStatePath(' variables. ')).toBe(false);
    });

    it('lists placeholders that are not state paths', () => {
        expect(nonStatePathPlaceholders('p_{variables.user.id}_{region}_{variables[0]}')).toEqual(['region']);
        expect(nonStatePathPlaceholders('static')).toEqual([]);
        expect(nonStatePathPlaceholders('p_{ variables.id }_{variables.}')).toEqual(['variables.']);
    });

    it('builds one hint per key template', () => {
        expect(keyTemplateHint('p_{variables.id}')).toBeNull();
        expect(keyTemplateHint('p_{user_id}')).toBe('Not a state path: {user_id}. Use e.g. {variables.user.id}');
        expect(keyTemplateHint('p_{}_{user_id}')).toBe('Empty or unbalanced placeholder. Use e.g. {variables.user.id}');
    });

    it('keeps only keys when switching modes, so a read alias never lands in a write value path', () => {
        const entries = [{ alias: 'a', key: 'k1', default: 1 }];
        expect(reshapeEntriesForMode(entries, 'delete')).toEqual([{ key: 'k1' }]);
        expect(reshapeEntriesForMode(entries, 'write')).toEqual([{ key: 'k1', value: '' }]);
        expect(reshapeEntriesForMode([{ key: 'k1', value: 'variables.a' }], 'read')).toEqual([
            { alias: '', key: 'k1' },
        ]);
    });

    it('parses defaults as JSON, falling back to text', () => {
        expect(parseDefaultValue('')).toBeUndefined();
        expect(parseDefaultValue('42')).toBe(42);
        expect(parseDefaultValue('{"a":1}')).toEqual({ a: 1 });
        expect(parseDefaultValue('hello')).toBe('hello');
    });

    it('builds existence badges per mode', () => {
        const recorded = { exists: true, value_preview: '"v"', updated_at: '2026-09-23T10:00:00Z' };
        const missing = { exists: false, value_preview: null, updated_at: null };

        expect(existenceBadge('read', 'k', recorded)).toEqual({ kind: 'recorded', label: 'recorded', tooltip: '"v"' });
        expect(existenceBadge('read', 'k', missing).label).toBe('not recorded — returns default');
        expect(existenceBadge('write', 'k', recorded).label).toBe('exists — will overwrite');
        expect(existenceBadge('write', 'k', missing).label).toBe('new key');
        expect(existenceBadge('delete', 'k', missing).label).toBe('not recorded — no-op');
        expect(existenceBadge('read', 'p_{id}', undefined).kind).toBe('dynamic');
        // A malformed key fails at run time: no lookup, and no badge claiming it is new or dynamic.
        expect(existenceBadge('write', 'p_{', missing).kind).toBe('unknown');
        expect(existenceBadge('write', 'p_{}', undefined).kind).toBe('unknown');
        expect(existenceBadge('read', 'k', undefined).kind).toBe('unknown');
    });

    it('normalises entries to one key order per mode', () => {
        // jsonb returns object keys sorted (shorter first), so a stored read entry loads as {key, alias, default}.
        const fromDatabase = normalizeEntry({ key: 'k', alias: 'a', default: 1 }, 'read');
        const fromPanel = normalizeEntry({ alias: 'a', key: 'k', default: 1 }, 'read');

        expect(JSON.stringify(fromDatabase)).toBe(JSON.stringify(fromPanel));
        expect(JSON.stringify(fromDatabase)).toBe('{"alias":"a","key":"k","default":1}');
        expect(normalizeEntry({ key: 'k', alias: 'a', default: undefined }, 'read')).toStrictEqual({
            alias: 'a',
            key: 'k',
        });
        expect(normalizeEntry({ key: 'k', alias: 'a', default: null }, 'read')).toStrictEqual({
            alias: 'a',
            key: 'k',
            default: null,
        });
        expect(JSON.stringify(normalizeEntry({ value: 'v', key: 'k' }, 'write'))).toBe('{"key":"k","value":"v"}');
        expect(normalizeEntry({ alias: 'a', key: 'k', default: 1 }, 'delete')).toStrictEqual({ key: 'k' });
    });

    it('compares lookup requests by table and keys', () => {
        expect(isSameLookupRequest({ table: 1, staticKeys: ['a'] }, { table: 1, staticKeys: ['a'] })).toBe(true);
        expect(isSameLookupRequest({ table: 1, staticKeys: ['a'] }, { table: 2, staticKeys: ['a'] })).toBe(false);
        expect(isSameLookupRequest({ table: 1, staticKeys: ['a'] }, { table: 1, staticKeys: ['a', 'b'] })).toBe(false);
    });
});
