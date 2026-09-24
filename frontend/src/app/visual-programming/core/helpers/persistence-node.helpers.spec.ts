import {
    existenceBadge,
    extractPlaceholders,
    isSameLookupRequest,
    isStaticKey,
    missingPlaceholders,
    normalizeEntry,
    parseDefaultValue,
    reshapeEntriesForMode,
} from './persistence-node.helpers';

describe('persistence node helpers', () => {
    it('extracts placeholders', () => {
        expect(extractPlaceholders('profile_{user_id}_{region}')).toEqual(['user_id', 'region']);
        expect(extractPlaceholders('static')).toEqual([]);
    });

    it('detects static keys', () => {
        expect(isStaticKey('config')).toBe(true);
        expect(isStaticKey('profile_{user_id}')).toBe(false);
    });

    it('lists placeholders missing from the input map', () => {
        expect(missingPlaceholders('p_{user_id}_{region}', ['user_id'])).toEqual(['region']);
    });

    it('keeps only keys when switching modes', () => {
        const entries = [{ alias: 'a', key: 'k1', default: 1 }];
        expect(reshapeEntriesForMode(entries, 'delete')).toEqual([{ key: 'k1' }]);
        expect(reshapeEntriesForMode(entries, 'write')).toEqual([{ key: 'k1', value: '' }]);
        expect(reshapeEntriesForMode([{ key: 'k1' }], 'read')).toEqual([{ alias: '', key: 'k1' }]);
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
