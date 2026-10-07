import { BridgeMethodContextV2, BridgeMethodDefinition, BridgeMethodTable } from './bridge-method';
import { BRIDGE_V1_METHODS } from './v1/bridge-v1.methods';
import { BRIDGE_V2_METHODS } from './v2/bridge-v2.methods';

/**
 * Every bridge version this EpicStaff serves, keyed by the plugin's `bridge_version`. Only ever add.
 * The host hands every method the full v2 context; a v1 method simply uses less of it.
 */
export const BRIDGE_TABLES: Readonly<Record<number, BridgeMethodTable<BridgeMethodContextV2>>> = Object.freeze({
    1: BRIDGE_V1_METHODS,
    2: BRIDGE_V2_METHODS,
});

export function isSupportedBridgeVersion(version: number): boolean {
    return Object.hasOwn(BRIDGE_TABLES, version);
}

/**
 * Own-property lookup, so a method named `constructor` or `__proto__` never resolves. A v1 method
 * needs only the v1 context, so v1 callers (the frozen v1 contract spec) may pass just that.
 */
export function findBridgeMethod(version: 1, method: string): BridgeMethodDefinition | null;
export function findBridgeMethod(version: number, method: string): BridgeMethodDefinition<BridgeMethodContextV2> | null;
export function findBridgeMethod(
    version: number,
    method: string
): BridgeMethodDefinition<BridgeMethodContextV2> | null {
    if (!isSupportedBridgeVersion(version)) return null;
    const table = BRIDGE_TABLES[version];
    return Object.hasOwn(table, method) ? table[method] : null;
}
