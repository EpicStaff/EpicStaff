/**
 * Validates persistent_variables in domain variables JSON.
 * Ensures paths in user/organization arrays exist in variables.context
 * and checks for duplicates (cross-array and within-array).
 */

export type TargetArray = 'user' | 'organization';

export interface WithinArrayDuplicate {
    path: string;
    array: TargetArray;
}

export interface PersistentVariablesValidationResult {
    pathValidationErrors: string[];
    crossArrayDuplicatePaths: string[];
    withinArrayDuplicatePaths: WithinArrayDuplicate[];
    numericSegmentPathErrors: string[];
}

export const EMPTY_VALIDATION_RESULT: PersistentVariablesValidationResult = {
    pathValidationErrors: [],
    crossArrayDuplicatePaths: [],
    withinArrayDuplicatePaths: [],
    numericSegmentPathErrors: [],
};

export function hasValidationErrors(result: PersistentVariablesValidationResult): boolean {
    return (
        result.pathValidationErrors.length > 0 ||
        result.crossArrayDuplicatePaths.length > 0 ||
        result.withinArrayDuplicatePaths.length > 0 ||
        result.numericSegmentPathErrors.length > 0
    );
}

export function formatValidationMessages(result: PersistentVariablesValidationResult): string[] {
    const messages: string[] = [];

    for (const path of result.pathValidationErrors) {
        messages.push(`Path ${path} in persistent_variables does not exist in variables`);
    }

    for (const path of result.crossArrayDuplicatePaths) {
        messages.push(`Path ${path} cannot be in both user and organization`);
    }

    for (const item of result.withinArrayDuplicatePaths) {
        messages.push(`Path ${item.path} is duplicated in ${item.array} array`);
    }

    for (const path of result.numericSegmentPathErrors) {
        messages.push(`Path ${path}: use object properties instead of array indices (e.g. .0)`);
    }

    return messages;
}

const CONTEXT_PREFIX = 'context.';

/**
 * Extracts context paths (e.g. "context.foo.bar") from an array.
 */
export function extractPathsFromArray(arr: unknown): Set<string> {
    if (!Array.isArray(arr)) return new Set();
    const set = new Set<string>();
    for (const item of arr) {
        const path = typeof item === 'string' ? item.trim() : null;
        if (path && path.startsWith(CONTEXT_PREFIX)) {
            set.add(path);
        }
    }
    return set;
}

/**
 * Returns paths that appear more than once in the array.
 */
export function findDuplicatesWithinArray(arr: unknown): string[] {
    if (!Array.isArray(arr)) return [];
    const seen = new Set<string>();
    const duplicates = new Set<string>();
    for (const item of arr) {
        const path = typeof item === 'string' ? item.trim() : null;
        if (path && path.startsWith(CONTEXT_PREFIX)) {
            if (seen.has(path)) {
                duplicates.add(path);
            } else {
                seen.add(path);
            }
        }
    }
    return Array.from(duplicates);
}

/**
 * Checks if a path exists in the object using path parts (without "context." prefix).
 */
export function pathExistsInObject(obj: unknown, pathParts: string[]): boolean {
    if (obj === null || obj === undefined) return false;
    if (pathParts.length === 0) return true;
    let current: unknown = obj;
    for (const part of pathParts) {
        if (current === null || current === undefined || typeof current !== 'object') {
            return false;
        }
        if (!Object.prototype.hasOwnProperty.call(current, part)) {
            return false;
        }
        current = (current as Record<string, unknown>)[part];
    }
    return true;
}

function hasNumericSegment(path: string): boolean {
    const pathParts = path.slice(CONTEXT_PREFIX.length).split('.');
    return pathParts.some((part) => /^\d+$/.test(part));
}

/**
 * Validates paths in persistent_variables against variables.context.
 *
 * @param json - JSON string of domain variables (variables + persistent_variables)
 * @returns Validation result with all error categories
 */
export function validatePersistentVariables(json: string): PersistentVariablesValidationResult {
    const result: PersistentVariablesValidationResult = {
        pathValidationErrors: [],
        crossArrayDuplicatePaths: [],
        withinArrayDuplicatePaths: [],
        numericSegmentPathErrors: [],
    };

    try {
        const parsed = JSON.parse(json);
        const context = parsed?.variables?.context;
        const pv = parsed?.persistent_variables;

        if (!pv || typeof pv !== 'object') {
            return result;
        }

        const userPaths = extractPathsFromArray(pv.user);
        const orgPaths = extractPathsFromArray(pv.organization);
        const userWithinDupes = findDuplicatesWithinArray(pv.user);
        const orgWithinDupes = findDuplicatesWithinArray(pv.organization);

        result.withinArrayDuplicatePaths.push(
            ...userWithinDupes.map((path) => ({ path, array: 'user' as const })),
            ...orgWithinDupes.map((path) => ({
                path,
                array: 'organization' as const,
            }))
        );

        for (const path of userPaths) {
            if (orgPaths.has(path)) {
                result.crossArrayDuplicatePaths.push(path);
            }
            if (hasNumericSegment(path)) {
                result.numericSegmentPathErrors.push(path);
                continue;
            }
            const pathParts = path.slice(CONTEXT_PREFIX.length).split('.');
            if (!pathExistsInObject(context, pathParts)) {
                result.pathValidationErrors.push(path);
            }
        }

        for (const path of orgPaths) {
            if (!userPaths.has(path)) {
                if (hasNumericSegment(path)) {
                    result.numericSegmentPathErrors.push(path);
                    continue;
                }
                const pathParts = path.slice(CONTEXT_PREFIX.length).split('.');
                if (!pathExistsInObject(context, pathParts)) {
                    result.pathValidationErrors.push(path);
                }
            }
        }
    } catch {
        // Invalid JSON – return empty result (JSON validity is handled elsewhere)
    }

    return result;
}
