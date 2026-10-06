import { BridgeMethodDefinition, BridgeMethodTable } from './bridge-method';
import { BRIDGE_V1_METHODS } from './v1/bridge-v1.methods';

/** Every bridge version this EpicStaff serves, keyed by the plugin's `bridge_version`. Only ever add. */
export const BRIDGE_TABLES: Readonly<Record<number, BridgeMethodTable>> = Object.freeze({ 1: BRIDGE_V1_METHODS });

export function isSupportedBridgeVersion(version: number): boolean {
    return Object.hasOwn(BRIDGE_TABLES, version);
}

/** Own-property lookup, so a method named `constructor` or `__proto__` never resolves. */
export function findBridgeMethod(version: number, method: string): BridgeMethodDefinition | null {
    if (!isSupportedBridgeVersion(version)) return null;
    const table = BRIDGE_TABLES[version];
    return Object.hasOwn(table, method) ? table[method] : null;
}
