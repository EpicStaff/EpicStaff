import { PluginUiSessionAccessEntry } from '../models/plugin.model';
import { aliasForResource, assertAnyGrant, buildAccessPolicy, describeAccess, resolveAlias } from './access-policy';
import { BridgeError } from './bridge-protocol';

const CHAT: PluginUiSessionAccessEntry = {
    alias: 'chat',
    type: 'flow',
    actions: ['run', 'sessions.read'],
    resource_id: 42,
};

const CONVERSATIONS: PluginUiSessionAccessEntry = {
    alias: 'conversations',
    type: 'key_value_table',
    actions: ['read'],
    resource_id: 5,
};

function expectBridgeError(action: () => unknown, code: string): void {
    let thrown: unknown = null;
    try {
        action();
    } catch (error) {
        thrown = error;
    }
    expect(thrown).toBeInstanceOf(BridgeError);
    expect((thrown as BridgeError).code).toBe(code);
}

describe('access policy', () => {
    it('resolves a granted alias and action to the database id', () => {
        const policy = buildAccessPolicy([CHAT]);

        expect(resolveAlias(policy, 'chat', 'flow', 'run')).toBe(42);
        expect(resolveAlias(policy, 'chat', 'flow', 'sessions.read')).toBe(42);
    });

    it('answers forbidden for an unknown alias', () => {
        const policy = buildAccessPolicy([CHAT]);

        expectBridgeError(() => resolveAlias(policy, 'billing', 'flow', 'run'), 'forbidden');
        expectBridgeError(() => resolveAlias(policy, 42, 'flow', 'run'), 'forbidden');
        expectBridgeError(() => resolveAlias(policy, undefined, 'flow', 'run'), 'forbidden');
    });

    it('answers forbidden for an action the entry does not grant', () => {
        const policy = buildAccessPolicy([CHAT]);

        expectBridgeError(() => resolveAlias(policy, 'chat', 'flow', 'sessions.stop'), 'forbidden');
    });

    it('treats an entry whose flow was deleted as forbidden', () => {
        const policy = buildAccessPolicy([{ ...CHAT, resource_id: null }]);

        expectBridgeError(() => resolveAlias(policy, 'chat', 'flow', 'run'), 'forbidden');
        expect(describeAccess(policy)).toEqual([]);
    });

    it('never resolves prototype keys as aliases', () => {
        const policy = buildAccessPolicy([CHAT]);

        for (const alias of ['__proto__', 'constructor', 'toString', 'hasOwnProperty']) {
            expectBridgeError(() => resolveAlias(policy, alias, 'flow', 'run'), 'forbidden');
        }
    });

    it('keeps the first of duplicate aliases and drops unknown actions', () => {
        const policy = buildAccessPolicy([
            { ...CHAT, actions: ['run', 'delete' as never] },
            { ...CHAT, resource_id: 99, actions: ['sessions.stop'] },
        ]);

        expect(resolveAlias(policy, 'chat', 'flow', 'run')).toBe(42);
        expectBridgeError(() => resolveAlias(policy, 'chat', 'flow', 'sessions.stop'), 'forbidden');
        expect(describeAccess(policy)).toEqual([{ alias: 'chat', type: 'flow', actions: ['run'] }]);
    });

    it('finds the alias for a session flow only with the needed action', () => {
        const policy = buildAccessPolicy([CHAT]);

        expect(aliasForResource(policy, 'flow', 42, 'sessions.read')).toBe('chat');
        expect(aliasForResource(policy, 'flow', 42, 'sessions.stop')).toBeNull();
        expect(aliasForResource(policy, 'flow', 7, 'sessions.read')).toBeNull();
    });

    it('rejects a session action no entry grants, before any lookup', () => {
        const policy = buildAccessPolicy([CHAT]);

        expect(() => assertAnyGrant(policy, 'sessions.read')).not.toThrow();
        expectBridgeError(() => assertAnyGrant(policy, 'sessions.stop'), 'forbidden');
    });

    it('describes the access list without database ids', () => {
        expect(describeAccess(buildAccessPolicy([CHAT]))).toEqual([
            { alias: 'chat', type: 'flow', actions: ['run', 'sessions.read'] },
        ]);
    });

    describe('per bridge version', () => {
        it('drops a key-value table entry for a bridge v1 page, with or without the version given', () => {
            for (const policy of [
                buildAccessPolicy([CHAT, CONVERSATIONS]),
                buildAccessPolicy([CHAT, CONVERSATIONS], 1),
            ]) {
                expect(describeAccess(policy)).toEqual([
                    { alias: 'chat', type: 'flow', actions: ['run', 'sessions.read'] },
                ]);
                expectBridgeError(() => resolveAlias(policy, 'conversations', 'key_value_table', 'read'), 'forbidden');
            }
        });

        it('grants read on a key-value table to a bridge v2 page', () => {
            const policy = buildAccessPolicy([CHAT, CONVERSATIONS], 2);

            expect(resolveAlias(policy, 'conversations', 'key_value_table', 'read')).toBe(5);
            expect(resolveAlias(policy, 'chat', 'flow', 'run')).toBe(42);
            expect(describeAccess(policy)).toEqual([
                { alias: 'chat', type: 'flow', actions: ['run', 'sessions.read'] },
                { alias: 'conversations', type: 'key_value_table', actions: ['read'] },
            ]);
        });

        it('keeps only the actions that fit the entry type', () => {
            const policy = buildAccessPolicy(
                [
                    { ...CHAT, actions: ['run', 'read'] },
                    { ...CONVERSATIONS, actions: ['read', 'run', 'sessions.read'] },
                ],
                2
            );

            expect(describeAccess(policy)).toEqual([
                { alias: 'chat', type: 'flow', actions: ['run'] },
                { alias: 'conversations', type: 'key_value_table', actions: ['read'] },
            ]);
            expectBridgeError(() => resolveAlias(policy, 'chat', 'flow', 'read'), 'forbidden');
            expectBridgeError(() => resolveAlias(policy, 'conversations', 'key_value_table', 'run'), 'forbidden');
        });

        it('never resolves an alias as another type than its own', () => {
            const policy = buildAccessPolicy([CHAT, CONVERSATIONS], 2);

            expectBridgeError(() => resolveAlias(policy, 'chat', 'key_value_table', 'read'), 'forbidden');
            expectBridgeError(() => resolveAlias(policy, 'conversations', 'flow', 'run'), 'forbidden');
        });

        it('grants nothing for a bridge version it does not know, or an unknown entry type', () => {
            expect(describeAccess(buildAccessPolicy([CHAT, CONVERSATIONS], 99))).toEqual([]);
            expect(describeAccess(buildAccessPolicy([{ ...CHAT, type: 'agent' as never }], 2))).toEqual([]);
        });

        it('treats a key-value table that was deleted as forbidden', () => {
            const policy = buildAccessPolicy([{ ...CONVERSATIONS, resource_id: null }], 2);

            expectBridgeError(() => resolveAlias(policy, 'conversations', 'key_value_table', 'read'), 'forbidden');
        });
    });
});
