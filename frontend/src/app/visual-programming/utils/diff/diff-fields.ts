import { isSameValue } from './normalize';
import { isNestedField, keyPrefixOf, Projection } from './semantic-projections';
import { FieldChange, FieldChangeStatus } from './types';

/**
 * What a restore changes in one matched node: compares the projection of the current canvas node with
 * the projection of the version node by walking both objects together (see `semantic-projections.ts`
 * for which values are walked):
 * - a nested field or a keyed item in the version only gives one `added` change for the whole, on the
 *   canvas only one `deleted` change for the whole;
 * - any other differing value gives one `changed` change (current → version). A declared nested field
 *   or collection whose value is not an object is compared whole the same way, so malformed data is
 *   never silently equal.
 * Changes follow the projection's key order, version keys first (the node as a restore leaves it).
 */
export function diffProjections(current: Projection, version: Projection): FieldChange[] {
    const changes: FieldChange[] = [];
    walkFields(current, version, { path: '', field: '' }, changes);
    return changes;
}

interface Location {
    /** Concrete path, e.g. `condition_groups[name=yes]`. */
    path: string;
    /** The same without item keys, e.g. `condition_groups[]`. */
    field: string;
}

function walkFields(
    current: Projection | null,
    version: Projection | null,
    parent: Location,
    changes: FieldChange[]
): void {
    for (const key of versionKeysFirst(current, version)) {
        const location = { path: join(parent.path, key), field: join(parent.field, key) };
        const currentValue = valueAt(current, key);
        const versionValue = valueAt(version, key);
        const keyPrefix = keyPrefixOf(location.field);

        if (keyPrefix !== undefined && bothObjectsOrNull(currentValue, versionValue)) {
            walkItems(currentValue, versionValue, location, keyPrefix, changes);
        } else if (isNestedField(location.field) && bothObjectsOrNull(currentValue, versionValue)) {
            walkGroup(currentValue, versionValue, location, changes);
        } else {
            compareWhole(location, currentValue, versionValue, changes);
        }
    }
}

function walkItems(
    currentItems: unknown,
    versionItems: unknown,
    collection: Location,
    keyPrefix: string,
    changes: FieldChange[]
): void {
    const current = asProjection(currentItems);
    const version = asProjection(versionItems);
    for (const key of versionKeysFirst(current, version)) {
        const item = { path: `${collection.path}[${keyPrefix}${key}]`, field: `${collection.field}[]` };
        const currentItem = valueAt(current, key);
        const versionItem = valueAt(version, key);
        if (bothObjectsOrNull(currentItem, versionItem)) {
            walkGroup(currentItem, versionItem, item, changes);
        } else {
            compareWhole(item, currentItem, versionItem, changes);
        }
    }
}

/**
 * A nested field or an item (each side an object or null): walked field by field when on both sides,
 * else one change for the whole: `added` when only the version has it, `deleted` when only the canvas has it.
 */
function walkGroup(currentValue: unknown, versionValue: unknown, group: Location, changes: FieldChange[]): void {
    const current = asProjection(currentValue);
    const version = asProjection(versionValue);
    if (current && version) {
        walkFields(current, version, group, changes);
    } else if (current || version) {
        changes.push(change(group, version ? 'added' : 'deleted', current, version));
    }
}

function compareWhole(location: Location, current: unknown, version: unknown, changes: FieldChange[]): void {
    if (!isSameValue(current, version)) changes.push(change(location, 'changed', current, version));
}

function change(location: Location, status: FieldChangeStatus, current: unknown, version: unknown): FieldChange {
    return { ...location, status, current, version };
}

function bothObjectsOrNull(current: unknown, version: unknown): boolean {
    return (current === null || asProjection(current) !== null) && (version === null || asProjection(version) !== null);
}

function versionKeysFirst(current: Projection | null, version: Projection | null): string[] {
    return [...new Set([...Object.keys(version ?? {}), ...Object.keys(current ?? {})])];
}

/** Own keys only (keyed collections may hold `__proto__`); a missing value reads as `null`. */
function valueAt(projection: Projection | null, key: string): unknown {
    return projection && Object.hasOwn(projection, key) ? (projection[key] ?? null) : null;
}

function asProjection(value: unknown): Projection | null {
    return value !== null && typeof value === 'object' && !Array.isArray(value) ? (value as Projection) : null;
}

function join(parent: string, key: string): string {
    return parent ? `${parent}.${key}` : key;
}
