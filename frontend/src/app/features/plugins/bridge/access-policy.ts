import { PluginAccessAction, PluginAccessTargetType, PluginUiSessionAccessEntry } from '../models/plugin.model';
import { BridgeAccessDescription, BridgeError } from './bridge-protocol';

type AccessTypeTable = Readonly<Partial<Record<PluginAccessTargetType, readonly PluginAccessAction[]>>>;

const FLOW_ACTIONS: readonly PluginAccessAction[] = ['run', 'sessions.read', 'sessions.stop'];

/**
 * Which access types, and which actions on each, a bridge version serves. An entry of a type the
 * plugin's bridge version doesn't know is dropped, and so is an action that doesn't fit the type:
 * a bridge v1 page never gets a key-value table, even if the access list names one. Only ever add.
 */
export const ACCESS_TYPES_BY_VERSION: Readonly<Record<number, AccessTypeTable>> = Object.freeze({
    1: Object.freeze({ flow: FLOW_ACTIONS }),
    2: Object.freeze({ flow: FLOW_ACTIONS, key_value_table: ['read'] as const }),
});

/** How an error message names an access type. */
const TYPE_LABELS: Readonly<Record<PluginAccessTargetType, string>> = {
    flow: 'flow',
    key_value_table: 'key-value table',
};

/** One usable access entry: an alias the plugin names, and the database row it stands for. */
export interface AccessGrant {
    readonly alias: string;
    readonly type: PluginAccessTargetType;
    readonly resourceId: number;
    readonly actions: ReadonlySet<PluginAccessAction>;
}

/**
 * What an open plugin page may reach through the bridge, keyed by alias.
 *
 * The bridge calls the API as the signed-in user, so the effective access is the user's own
 * permissions intersected with this list: the policy can only ever narrow what the user can do.
 */
export interface AccessPolicy {
    readonly grants: ReadonlyMap<string, AccessGrant>;
}

/**
 * The single mapping from the `ui-session` response's `access` list to the policy.
 *
 * An entry whose flow or table was deleted (`resource_id: null`), whose type `bridgeVersion` does
 * not serve, or that is malformed is left out, so any call naming it is `forbidden`. A duplicate
 * alias keeps its first entry. A `Map` (not an object) holds the grants so an alias such as
 * `__proto__` or `constructor` can never hit a prototype key. An unknown version grants nothing.
 */
export function buildAccessPolicy(entries: readonly PluginUiSessionAccessEntry[], bridgeVersion = 1): AccessPolicy {
    const types = Object.hasOwn(ACCESS_TYPES_BY_VERSION, bridgeVersion) ? ACCESS_TYPES_BY_VERSION[bridgeVersion] : {};
    const grants = new Map<string, AccessGrant>();
    for (const entry of entries) {
        if (typeof entry.alias !== 'string' || entry.alias === '' || grants.has(entry.alias)) continue;
        const allowedActions =
            typeof entry.type === 'string' && Object.hasOwn(types, entry.type) ? types[entry.type] : undefined;
        if (!allowedActions) continue;
        if (typeof entry.resource_id !== 'number' || !Number.isSafeInteger(entry.resource_id)) continue;
        if (!Array.isArray(entry.actions)) continue;
        grants.set(entry.alias, {
            alias: entry.alias,
            type: entry.type,
            resourceId: entry.resource_id,
            actions: new Set(entry.actions.filter((action) => allowedActions.includes(action))),
        });
    }
    return { grants };
}

/** Resolves an alias the plugin named to the database id it may act on, or throws `forbidden`. */
export function resolveAlias(
    policy: AccessPolicy,
    alias: unknown,
    type: PluginAccessTargetType,
    action: PluginAccessAction
): number {
    const grant = typeof alias === 'string' ? policy.grants.get(alias) : undefined;
    const label = TYPE_LABELS[type];
    if (!grant || grant.type !== type) {
        const name = typeof alias === 'string' ? `"${alias.slice(0, 64)}"` : 'with that alias';
        throw new BridgeError('forbidden', `This plugin has no access to a ${label} ${name}.`);
    }
    if (!grant.actions.has(action)) {
        throw new BridgeError('forbidden', `This plugin may not "${action}" the ${label} "${grant.alias}".`);
    }
    return grant.resourceId;
}

/** The alias granting `action` on the given database row, or `null` when the plugin has none. */
export function aliasForResource(
    policy: AccessPolicy,
    type: PluginAccessTargetType,
    resourceId: number,
    action: PluginAccessAction
): string | null {
    for (const grant of policy.grants.values()) {
        if (grant.type === type && grant.resourceId === resourceId && grant.actions.has(action)) return grant.alias;
    }
    return null;
}

/** Throws `forbidden` unless some entry grants `action`; lets a session call fail before any HTTP. */
export function assertAnyGrant(policy: AccessPolicy, action: PluginAccessAction): void {
    for (const grant of policy.grants.values()) {
        if (grant.actions.has(action)) return;
    }
    throw new BridgeError('forbidden', `This plugin may not "${action}" anything.`);
}

/** The access list as the plugin sees it in `init` and `bridge.hello`: aliases, no ids. */
export function describeAccess(policy: AccessPolicy): BridgeAccessDescription[] {
    return [...policy.grants.values()].map((grant) => ({
        alias: grant.alias,
        type: grant.type,
        actions: [...grant.actions],
    }));
}
