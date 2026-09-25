import { NodeType } from '@shared/models';

import { NodeModel } from '../models/node.model';
import { PersistenceEntry, PersistenceMode } from '../models/persistence-node.model';
import {
    existenceHint,
    extractPlaceholders,
    flowVariablePaths,
    hasValidPersistenceEntries,
    invalidPersistenceNodeMessages,
    isEmptyEntry,
    isMalformedKey,
    isSameLookupRequest,
    isStatePath,
    isStaticKey,
    isWriteSource,
    keyTemplateHint,
    nonStatePathPlaceholders,
    normalizeEntry,
    reshapeEntriesForMode,
    STATE_PATH,
    suggestStatePath,
    valuePathHint,
} from './persistence-node.helpers';

describe('persistence node helpers', () => {
    it('treats a row with nothing typed as empty, counting the untouched value prefill as nothing', () => {
        for (const row of [
            { key: '' },
            { key: '  ' },
            { key: '', value: 'variables.' },
            { key: '', value: ' variables. ' },
            { key: '', value: '' },
            { key: null, value: null },
        ]) {
            expect(isEmptyEntry(row)).toBe(true);
        }
        for (const row of [{ key: 'plan' }, { key: '', value: 'variables.a' }, { key: '', value: 'variables' }]) {
            expect(isEmptyEntry(row)).toBe(false);
        }
    });

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
        for (const key of ['static', 'p_{variables.id}', 'p_{user_id}_{variables.items[0]}']) {
            expect(isMalformedKey(key)).toBe(false);
        }
    });

    it('recognises well-formed state paths only, as crew and Django do', () => {
        for (const path of ['variables.a.b', 'variables.items[0]', 'variables.items[0][1].name', 'variables.a_b.0']) {
            expect(STATE_PATH.test(path)).toBe(true);
            expect(isStatePath(path)).toBe(true);
        }
        for (const path of [
            'name',
            'variables',
            'variables.',
            'variables[',
            'variables[0]',
            'variablesX.a',
            'state.variables.a',
            'variables.x|0',
            'variables.user-name',
            'variables.a b',
            'variables.a.',
            'variables.a..b',
            'variables.a[x]',
            'variables.caf\u00e9',
        ]) {
            expect(STATE_PATH.test(path)).toBe(false);
            expect(isStatePath(path)).toBe(false);
        }
        // Names starting with _ fit the pattern but are rejected.
        for (const path of ['variables._private', 'variables.user.__class__', 'variables.items[0]._x']) {
            expect(STATE_PATH.test(path)).toBe(true);
            expect(isStatePath(path)).toBe(false);
        }
        expect(isStatePath('  variables.a  ')).toBe(true);
        expect(isStatePath(' variables. ')).toBe(false);
    });

    it('checks a write source before its |default', () => {
        for (const text of ['variables.a', 'variables.a|0', 'variables.a|', ' variables.a |{"x": 1}']) {
            expect(isWriteSource(text)).toBe(true);
        }
        for (const text of ['variables.a-b|0', 'variables._a|0', '|0', 'a|variables.a']) {
            expect(isWriteSource(text)).toBe(false);
        }
    });

    it('lists placeholders that are not state paths', () => {
        expect(nonStatePathPlaceholders('p_{variables.user.id}_{region}_{variables[0]}')).toEqual([
            'region',
            'variables[0]',
        ]);
        expect(nonStatePathPlaceholders('static')).toEqual([]);
        expect(nonStatePathPlaceholders('p_{ variables.id }_{variables.}')).toEqual(['variables.']);
        expect(nonStatePathPlaceholders('p_{variables.user-id}_{variables._id}')).toEqual([
            'variables.user-id',
            'variables._id',
        ]);
    });

    it('suggests the state path a rootless path meant', () => {
        expect(suggestStatePath(' user_id ')).toBe('variables.user_id');
        expect(suggestStatePath('user.tags[0].name')).toBe('variables.user.tags[0].name');
        for (const text of [
            'variables',
            'variables.',
            'Variables.user.name',
            'user id',
            '.id',
            '[0]',
            '',
            '_id',
            'a._b',
        ]) {
            expect(suggestStatePath(text)).toBeNull();
        }
    });

    it('builds one key hint that says how to write the placeholders, from what was typed', () => {
        expect(keyTemplateHint('p_{variables.id}')).toBeNull();
        expect(keyTemplateHint('p_{user_id}')).toBe('Use {variables.user_id}');
        expect(keyTemplateHint('p_{user.id}_{items[0]}')).toBe('Use {variables.user.id}, {variables.items[0]}');
        expect(keyTemplateHint('{user_id}_{user_id}')).toBe('Use {variables.user_id}');
        expect(keyTemplateHint('p_{}_{user_id}')).toBe('Write placeholders as {variables.user.id}');
        expect(keyTemplateHint('p_{variables.}')).toBe('Write placeholders as {variables.user.id}');
        expect(keyTemplateHint('p_{user id}')).toBe('Write placeholders as {variables.user.id}');
        // Never suggests an index straight after `variables`: flow variables are a dict.
        expect(keyTemplateHint('p_{variables[0]}')).toBe('Write placeholders as {variables.user.id}');
        expect(keyTemplateHint('p_{variables.user-id}')).toBe(
            'Use letters, digits and _ in variable names, like variables.user_name'
        );
        expect(keyTemplateHint('p_{user id}_{variables._id}')).toBe("Variable names can't start with _");
    });

    it('builds a value path hint from what was typed', () => {
        for (const mode of ['read', 'write'] as const) {
            expect(valuePathHint('variables.user.name', mode)).toBeNull();
            expect(valuePathHint('', mode)).toBeNull();
            expect(valuePathHint('user.name', mode)).toBe('Use variables.user.name');
            expect(valuePathHint('variables.', mode)).toBe('Use a state path like variables.user.name');
            expect(valuePathHint('Variables.user.name', mode)).toBe('Use a state path like variables.user.name');
            expect(valuePathHint('user name', mode)).toBe('Use a state path like variables.user.name');
            expect(valuePathHint('variables[0]', mode)).toBe('Use a state path like variables.user.name');
            expect(valuePathHint('variables.user-name', mode)).toBe(
                'Use letters, digits and _ in variable names, like variables.user_name'
            );
            expect(valuePathHint('variables.a b', mode)).toBe(
                'Use letters, digits and _ in variable names, like variables.user_name'
            );
            expect(valuePathHint('variables.user._id', mode)).toBe("Variable names can't start with _");
        }
        expect(valuePathHint('variables.user|0', 'write')).toBeNull();
        expect(valuePathHint('user.name|0', 'write')).toBe('Use variables.user.name|0');
        expect(valuePathHint('variables._x|0', 'write')).toBe("Variable names can't start with _");
        expect(valuePathHint('variables.user|0', 'read')).toBe('Leave out the |default: a missing key reads None');
    });

    it('carries values between read and write, and restores remembered ones when leaving delete', () => {
        const nothingRemembered = (): undefined => undefined;
        const remembered = (key: string): string | undefined => (key === 'k1' ? 'variables.old' : undefined);

        expect(reshapeEntriesForMode([{ key: 'k1', value: 'variables.a' }], 'delete', nothingRemembered)).toEqual([
            { key: 'k1' },
        ]);
        expect(reshapeEntriesForMode([{ key: 'k1', value: 'variables.a' }], 'read', remembered)).toEqual([
            { key: 'k1', value: 'variables.a' },
        ]);
        expect(reshapeEntriesForMode([{ key: 'k1' }, { key: 'k2' }], 'write', remembered)).toEqual([
            { key: 'k1', value: 'variables.old' },
            { key: 'k2', value: 'variables.' },
        ]);
    });

    it('checks flow entries the way the panel does, so the flow save can refuse them', () => {
        const isValid = (mode: PersistenceMode, entries: PersistenceEntry[]): boolean =>
            hasValidPersistenceEntries({ persistence_table: 1, mode, entries });

        expect(isValid('delete', [{ key: 'profile_{variables.user.id}' }])).toBe(true);
        expect(isValid('write', [{ key: 'a', value: 'variables.a|0' }])).toBe(true);
        expect(isValid('write', [{ key: 'a', value: 'variables.a-b|0' }])).toBe(false);
        expect(isValid('read', [{ key: 'a', value: 'variables.a|0' }])).toBe(false);
        expect(isValid('read', [{ key: 'a', value: 'variables._a' }])).toBe(false);
        expect(isValid('delete', [{ key: 'p_{variables.user-id}' }])).toBe(false);
        expect(
            isValid('read', [
                { key: 'a', value: 'variables.a' },
                { key: 'b', value: 'variables.b' },
            ])
        ).toBe(true);
        expect(isValid('read', [])).toBe(true);

        // What a switch from delete leaves until the values are typed.
        expect(isValid('write', [{ key: 'profile_{variables.user.id}', value: 'variables.' }])).toBe(false);
        expect(
            isValid('read', [
                { key: 'a', value: 'variables.x' },
                { key: 'b', value: ' variables.x ' },
            ])
        ).toBe(false);
        expect(isValid('delete', [{ key: 'p_{user_id}' }])).toBe(false);
        expect(isValid('delete', [{ key: '  ' }])).toBe(false);
        expect(isValid('delete', [{ key: 'k'.repeat(513) }])).toBe(false);
    });

    it('names each persistence node the flow save must refuse, and no other node', () => {
        const persistence = (node_name: string, entries: PersistenceEntry[]): NodeModel =>
            ({
                type: NodeType.PERSISTENCE,
                node_name,
                data: { persistence_table: 1, mode: 'write', entries },
            }) as unknown as NodeModel;
        const nodes: NodeModel[] = [
            persistence('Ok', [{ key: 'a', value: 'variables.a' }]),
            persistence('Unfinished', [{ key: 'a', value: 'variables.' }]),
            { type: NodeType.PYTHON, node_name: 'Code', data: {} } as unknown as NodeModel,
        ];

        expect(invalidPersistenceNodeMessages(nodes)).toEqual(['"Unfinished" has invalid keys or variable paths']);
        expect(invalidPersistenceNodeMessages(nodes.slice(0, 1))).toEqual([]);
    });

    it('lists the flow variables as state paths, each parent first', () => {
        expect(flowVariablePaths({ variables: { user: { id: 1, tags: ['a'] }, plan: 'free', empty: null } })).toEqual([
            'variables.user',
            'variables.user.id',
            'variables.user.tags',
            'variables.plan',
            'variables.empty',
        ]);
        expect(flowVariablePaths({ variables: { 'user-name': 'x', _secret: { id: 1 }, ok: 1 } })).toEqual([
            'variables.ok',
        ]);
        expect(flowVariablePaths({})).toEqual([]);
        expect(flowVariablePaths({ variables: [1] })).toEqual([]);
    });

    it('builds existence hints per mode', () => {
        const stored = { exists: true, value_preview: '"v"', updated_at: '2026-09-23T10:00:00Z' };
        const missing = { exists: false, value_preview: null, updated_at: null };

        expect(existenceHint('read', stored)).toBe('Exists');
        expect(existenceHint('read', missing)).toBe('New key — reads None');
        expect(existenceHint('write', stored)).toBe('Exists — will overwrite');
        expect(existenceHint('write', missing)).toBe('New key');
        expect(existenceHint('delete', stored)).toBe('Exists');
        expect(existenceHint('delete', missing)).toBe('Not recorded — no-op');
        // Keys with placeholders or malformed keys are never looked up.
        expect(existenceHint('read', undefined)).toBeNull();
    });

    it('normalises entries to one key order per mode', () => {
        for (const mode of ['read', 'write'] as const) {
            expect(JSON.stringify(normalizeEntry({ value: 'v', key: 'k' }, mode))).toBe('{"key":"k","value":"v"}');
        }
        expect(normalizeEntry({ key: 'k', value: 'v' }, 'delete')).toStrictEqual({ key: 'k' });
    });

    it('compares lookup requests by table and keys', () => {
        expect(isSameLookupRequest({ table: 1, staticKeys: ['a'] }, { table: 1, staticKeys: ['a'] })).toBe(true);
        expect(isSameLookupRequest({ table: 1, staticKeys: ['a'] }, { table: 2, staticKeys: ['a'] })).toBe(false);
        expect(isSameLookupRequest({ table: 1, staticKeys: ['a'] }, { table: 1, staticKeys: ['a', 'b'] })).toBe(false);
    });
});
