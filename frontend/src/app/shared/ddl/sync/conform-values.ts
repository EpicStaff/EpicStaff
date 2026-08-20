import type { JsonObject, JsonValue } from './json-value';

/**
 * Reshape `user` (values a person actually typed) onto the structure of
 * `sample` (the DDL schema's generated sample): the result always has
 * `sample`'s shape, but keeps `user`'s values wherever their kind still fits.
 *
 * - A `null` in `sample` marks a recursion break (e.g. a cyclic class
 *   reference in `emitJson`) — there is no further structure to conform to,
 *   so the user's value passes through untouched.
 * - Object keys present only in `user` pass through as-is, so values typed
 *   during the debounce window are never dropped mid-sync.
 * - Arrays keep the user's length; each element is conformed against
 *   `sample`'s first element (or dropped back to null-shape if `sample` had
 *   no elements to model against).
 */
export function conformValuesToSample(sample: JsonValue, user: JsonValue): JsonValue {
    if (sample === null) return user;

    if (Array.isArray(sample)) {
        if (!Array.isArray(user)) return sample;
        // Arrays keep the user's length, not the sample's — preserve what the user typed; only element shapes are conformed (against sample[0]).
        const elementSample = sample.length > 0 ? sample[0] : null;
        return user.map((item) => conformValuesToSample(elementSample, item));
    }

    if (isPlainObject(sample)) {
        if (!isPlainObject(user)) return sample;
        return conformObject(sample, user);
    }

    // `sample` is a scalar: keep the user's value only when its kind matches.
    return isSameScalarKind(sample, user) ? user : sample;
}

function conformObject(sample: JsonObject, user: JsonObject): JsonObject {
    const result: JsonObject = {};

    for (const key of Object.keys(sample)) {
        result[key] = key in user ? conformValuesToSample(sample[key], user[key]) : sample[key];
    }
    for (const key of Object.keys(user)) {
        if (!(key in sample)) result[key] = user[key];
    }

    return result;
}

function isSameScalarKind(sample: JsonValue, user: JsonValue): boolean {
    return user !== null && typeof sample === typeof user;
}

function isPlainObject(value: JsonValue): value is JsonObject {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}
