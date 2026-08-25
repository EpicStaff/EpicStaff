const IDENTITY_KEYS = new Set(['id', 'temp_id', 'graph']);

export function buildPartialNodePayload(
    prev: Record<string, unknown>,
    next: Record<string, unknown>
): { node: Record<string, unknown>; changed_fields: string[] } {
    const changed: string[] = [];
    for (const key of Object.keys(next)) {
        if (IDENTITY_KEYS.has(key)) continue;
        if (JSON.stringify(next[key]) != JSON.stringify(prev[key])) {
            changed.push(key);
        }
    }
    const node: Record<string, unknown> = {};
    if (next['id'] != null) node['id'] = next['id'];
    if (next['temp_id'] != null) node['temp_id'] = next['temp_id'];
    for (const key of changed) node[key] = next[key];
    return { node, changed_fields: changed };
}

export function mergeNodeEntry(
    base: Record<string, unknown>,
    overlay: Record<string, unknown>
): Record<string, unknown> {
    const merged: Record<string, unknown> = { ...base };
    for (const key of Object.keys(overlay)) {
        const overlayVal = overlay[key];
        const baseVal = merged[key];
        if (
            key === 'metadata' &&
            baseVal &&
            typeof baseVal === 'object' &&
            !Array.isArray(baseVal) &&
            overlayVal &&
            typeof overlayVal === 'object' &&
            !Array.isArray(overlayVal)
        ) {
            merged[key] = { ...(baseVal as object), ...(overlayVal as object) };
        } else {
            merged[key] = overlayVal;
        }
    }
    return merged;
}
