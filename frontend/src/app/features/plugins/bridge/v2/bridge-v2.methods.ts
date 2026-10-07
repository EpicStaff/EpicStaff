/**
 * Plugin bridge v2 — PUBLIC CONTRACT. Installed plugins call these methods by name.
 *
 * Never change v2 once released: not a method name, a param, a result key, an error code or the
 * HTTP call behind it. Add a `v3/` table instead. `bridge-v2.contract.spec.ts` pins it.
 *
 * v2 = every v1 method, unchanged (the very same definitions), plus:
 * - `kv.list` / `kv.get`: read a key-value table the plugin was granted `read` on, named by alias.
 *   The page never sees a database id: entry and table ids are stripped, and `kv.get` resolves the
 *   key to an entry itself, then checks the entry it read belongs to that table and key.
 * - `nav.changed`: the page reports its own path; EpicStaff mirrors it in its address bar.
 * The host also pushes `nav.navigate` and `theme.changed` events (see `PluginBridgeHost`).
 */

import { map, of, switchMap } from 'rxjs';

import { describeAccess, resolveAlias } from '../access-policy';
import { BridgeMethodContextV2, BridgeMethodDefinition, BridgeMethodTable } from '../bridge-method';
import { BRIDGE_V2_LIMITS, BridgeError, BridgeParams, isRecord } from '../bridge-protocol';
import { BridgeKeyValueListQuery, BridgeKeyValueOrdering } from '../plugin-bridge-api.service';
import { canonicalNavPath } from '../plugin-nav-path.util';
import { BRIDGE_V1_METHODS } from '../v1/bridge-v1.methods';

/** One answer for every unreachable entry, so the page can't tell a missing key from a foreign one. */
const ENTRY_NOT_FOUND_MESSAGE = 'No entry with that key in this table.';

/** The key-value tables' own key rule: a letter or `_`, then letters, digits or `_`. */
const KEY_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/;

const ORDERINGS: readonly BridgeKeyValueOrdering[] = ['key', '-key', 'updated_at', '-updated_at'];

/** The keys of one `kv.list` item: everything else the API returns (ids, who wrote it) is dropped. */
const LIST_ITEM_KEYS = ['key', 'value_preview', 'value_truncated', 'created_at', 'updated_at'] as const;

export const BRIDGE_V2_METHODS = Object.freeze({
    /** → `{bridge_version, plugin: {id, version, name}, access: [{alias, type, actions}], methods}` */
    'bridge.hello': {
        paramKeys: [],
        resultKeys: ['bridge_version', 'plugin', 'access', 'methods'],
        invoke: (context) =>
            of({
                bridge_version: context.bridgeVersion,
                plugin: { ...context.plugin },
                access: describeAccess(context.access),
                methods: listMethodNames(),
            }),
    },

    'flows.run': BRIDGE_V1_METHODS['flows.run'],
    'sessions.get': BRIDGE_V1_METHODS['sessions.get'],
    'sessions.subscribe': BRIDGE_V1_METHODS['sessions.subscribe'],
    'sessions.unsubscribe': BRIDGE_V1_METHODS['sessions.unsubscribe'],
    'sessions.stop': BRIDGE_V1_METHODS['sessions.stop'],

    /**
     * `{table: alias, search?, ordering?, limit?, offset?}` →
     * `GET /api/key-value-table-entries/?table=<id>&ordering=&limit=&offset=[&search=]` →
     * `{count, items: [{key, value_preview, value_truncated, created_at, updated_at}]}`
     */
    'kv.list': {
        paramKeys: ['table', 'search', 'ordering', 'limit', 'offset'],
        resultKeys: ['count', 'items'],
        invoke: (context, params) => {
            const search = optionalText(params, 'search');
            const ordering = optionalOrdering(params);
            const limit = optionalInteger(
                params,
                'limit',
                1,
                BRIDGE_V2_LIMITS.maxKeyValuePageSize,
                BRIDGE_V2_LIMITS.defaultKeyValuePageSize
            );
            const offset = optionalInteger(params, 'offset', 0, Number.MAX_SAFE_INTEGER, 0);
            const tableId = resolveAlias(context.access, params['table'], 'key_value_table', 'read');
            const query: BridgeKeyValueListQuery = { tableId, ordering, limit, offset, search };
            return context.api.listKeyValueEntries(query).pipe(map((response) => toListResult(response, tableId)));
        },
    },

    /**
     * `{table: alias, key}` → `GET …/key-value-table-entries/?table=<id>&key=<key>&limit=1`, then
     * `GET …/key-value-table-entries/<entry id>/` → `{key, value, created_at, updated_at}`
     */
    'kv.get': {
        paramKeys: ['table', 'key'],
        resultKeys: ['key', 'value', 'created_at', 'updated_at'],
        invoke: (context, params) => {
            const key = requireKey(params);
            const tableId = resolveAlias(context.access, params['table'], 'key_value_table', 'read');
            return context.api.findKeyValueEntryId(tableId, key).pipe(
                switchMap((entryId) => {
                    if (entryId === null) throw new BridgeError('not_found', ENTRY_NOT_FOUND_MESSAGE);
                    return context.api.getKeyValueEntry(entryId);
                }),
                map((entry: unknown) => {
                    // Pinned to the granted table and the asked key, whatever the lookup returned.
                    if (!isRecord(entry) || entry['table'] !== tableId || entry['key'] !== key) {
                        throw new BridgeError('not_found', ENTRY_NOT_FOUND_MESSAGE);
                    }
                    return {
                        key,
                        value: entry['value'] ?? null,
                        created_at: entry['created_at'],
                        updated_at: entry['updated_at'],
                    };
                })
            );
        },
    },

    /** `{path, replace?}` → EpicStaff's router (no HTTP) → `{}` */
    'nav.changed': {
        paramKeys: ['path', 'replace'],
        resultKeys: [],
        invoke: (context, params) => {
            const path = canonicalNavPath(params['path']);
            if (path === null) {
                throw new BridgeError(
                    'bad_request',
                    `"path" must be an absolute path of at most ${BRIDGE_V2_LIMITS.maxNavPathLength} characters, like "/items/42?sort=key".`
                );
            }
            const replace = params['replace'] ?? false;
            if (typeof replace !== 'boolean') {
                throw new BridgeError('bad_request', '"replace" must be true or false.');
            }
            context.consumeNavigation();
            context.reportNavigation(path, replace);
            return of({});
        },
    },
} as const satisfies Readonly<
    Record<string, BridgeMethodDefinition<BridgeMethodContextV2>>
>) satisfies BridgeMethodTable<BridgeMethodContextV2>;

export type BridgeV2MethodName = keyof typeof BRIDGE_V2_METHODS;

function listMethodNames(): string[] {
    return Object.keys(BRIDGE_V2_METHODS);
}

function toListResult(response: unknown, tableId: number): { count: number; items: Record<string, unknown>[] } {
    if (!isRecord(response) || !Array.isArray(response['results'])) {
        throw new BridgeError('internal', 'EpicStaff did not return a list of entries.');
    }
    const count = response['count'];
    const items = response['results']
        .filter((item: unknown): item is Record<string, unknown> => isRecord(item) && item['table'] === tableId)
        .map((item) => Object.fromEntries(LIST_ITEM_KEYS.map((key) => [key, item[key]])));
    return { count: typeof count === 'number' ? count : items.length, items };
}

function requireKey(params: BridgeParams): string {
    const key = params['key'];
    if (typeof key !== 'string' || key.length > BRIDGE_V2_LIMITS.maxKeyValueTextLength || !KEY_PATTERN.test(key)) {
        throw new BridgeError(
            'bad_request',
            `"key" must be a letter or "_" followed by letters, digits or "_", at most ${BRIDGE_V2_LIMITS.maxKeyValueTextLength} characters.`
        );
    }
    return key;
}

function optionalText(params: BridgeParams, name: string): string {
    const value = params[name];
    if (value === undefined) return '';
    if (typeof value !== 'string' || value.length > BRIDGE_V2_LIMITS.maxKeyValueTextLength) {
        throw new BridgeError(
            'bad_request',
            `"${name}" must be text of at most ${BRIDGE_V2_LIMITS.maxKeyValueTextLength} characters.`
        );
    }
    return value;
}

function optionalOrdering(params: BridgeParams): BridgeKeyValueOrdering {
    const value = params['ordering'];
    if (value === undefined) return 'key';
    const ordering = ORDERINGS.find((candidate) => candidate === value);
    if (!ordering) {
        throw new BridgeError('bad_request', `"ordering" must be one of ${ORDERINGS.join(', ')}.`);
    }
    return ordering;
}

function optionalInteger(params: BridgeParams, name: string, min: number, max: number, fallback: number): number {
    const value = params[name];
    if (value === undefined) return fallback;
    if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < min || value > max) {
        const range = max === Number.MAX_SAFE_INTEGER ? `of at least ${min}` : `from ${min} to ${max}`;
        throw new BridgeError('bad_request', `"${name}" must be a whole number ${range}.`);
    }
    return value;
}
