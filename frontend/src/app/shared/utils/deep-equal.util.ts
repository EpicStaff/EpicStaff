/**
 * Recursive structural equality check for primitives, Dates, arrays, and plain objects.
 * Does not special-case Map, Set, RegExp, or circular references.
 */
export function deepEqual(a: unknown, b: unknown): boolean {
    if (Object.is(a, b)) return true;

    // SameValueZero: treat +0 and -0 as equal (Object.is treats them as distinct).
    if (typeof a === 'number' && typeof b === 'number' && a === 0 && b === 0) return true;

    if (a === null || a === undefined || b === null || b === undefined) {
        return a === b;
    }

    if (a instanceof Date && b instanceof Date) {
        return a.getTime() === b.getTime();
    }

    if (Array.isArray(a) !== Array.isArray(b)) return false;

    if (Array.isArray(a) && Array.isArray(b)) {
        if (a.length !== b.length) return false;
        return a.every((item, i) => deepEqual(item, b[i]));
    }

    if (typeof a === 'object' && typeof b === 'object') {
        const aObj = a as Record<string, unknown>;
        const bObj = b as Record<string, unknown>;
        const aKeys = Object.keys(aObj);
        const bKeys = Object.keys(bObj);
        if (aKeys.length !== bKeys.length) return false;

        return aKeys.every((key) => deepEqual(aObj[key], bObj[key]));
    }

    return false;
}
