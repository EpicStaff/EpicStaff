import { AgentSearchConfigs } from '@shared/models';

/**
 * Value normalization shared by the semantic projections. Both sides of a diff go through the
 * same functions, so a value that only differs by representation compares equal.
 */

/** Restore and import renumber nodes, so the ` #N` counter suffix is not part of the name. */
export function stripNodeNumberSuffix(name: string | null | undefined): string {
    return (name ?? '').replace(/ #\d+$/, '');
}

export function orNull<T>(value: T | null | undefined): T | null {
    return value ?? null;
}

/** An empty string and a missing value are the same thing for optional text settings. */
export function emptyToNull(value: string | null | undefined): string | null {
    return value ? value : null;
}

/** Sorted by code point, so the result does not depend on the locale. */
export function sortedStrings(values: readonly string[] | null | undefined): string[] {
    return [...(values ?? [])].map(String).sort();
}

export function sortedNumbers(values: readonly number[] | null | undefined): number[] {
    return [...(values ?? [])].sort((left, right) => left - right);
}

/** Python libraries: the export stores a space-separated string, the live API a list. */
export function toLibraryList(libraries: string | readonly string[] | null | undefined): string[] {
    const list = typeof libraries === 'string' ? libraries.split(/\s+/) : [...(libraries ?? [])];
    return sortedStrings(list.map((library) => library.trim()).filter(Boolean));
}

/** Decimal columns arrive as strings (`"0.70"`) from the export and as rounded floats from the live API. */
export function roundDecimal(value: number | string | null | undefined, places = 2): number | null {
    if (value === null || value === undefined || value === '') return null;
    const number = Number(value);
    if (!Number.isFinite(number)) return null;
    const factor = 10 ** places;
    return Math.round(number * factor) / factor;
}

/** An unordered list of objects, in a fixed order. */
export function sortByCanonicalJson<T>(values: readonly T[] | null | undefined): T[] {
    return [...(values ?? [])]
        .map((value) => ({ value, json: stableStringify(value) }))
        .sort((left, right) => compareCodePoints(left.json, right.json))
        .map(({ value }) => value);
}

const WEEKDAY_ORDER = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];

/** Weekdays as a set, shown in calendar order. */
export function sortWeekdays(weekdays: readonly string[] | null | undefined): string[] {
    const rank = (day: string): number => {
        const index = WEEKDAY_ORDER.indexOf(day);
        return index === -1 ? WEEKDAY_ORDER.length : index;
    };
    return [...(weekdays ?? [])].sort((left, right) => rank(left) - rank(right) || compareCodePoints(left, right));
}

/** Knowledge search configs with the similarity threshold rounded and absent blocks as null. */
export function normalizeSearchConfigs(configs: AgentSearchConfigs | null | undefined): unknown {
    const naive = configs?.naive ?? null;
    const graph = configs?.graph ?? null;
    if (!naive && !graph) return null;
    return {
        naive: naive
            ? {
                  search_limit: orNull(naive.search_limit),
                  similarity_threshold: roundDecimal(naive.similarity_threshold),
                  is_suggested: naive.is_suggested ?? false,
              }
            : null,
        graph: graph
            ? {
                  search_method: orNull(graph.search_method),
                  basic: orNull(graph.basic),
                  local: orNull(graph.local),
                  global: orNull(graph.global),
                  drift: orNull(graph.drift),
              }
            : null,
    };
}

/** JSON with object keys sorted, so key order never makes two values differ. `undefined` reads as `null`. */
export function stableStringify(value: unknown): string {
    return (
        JSON.stringify(value, (_key, nested: unknown) =>
            isPlainObject(nested)
                ? Object.fromEntries(Object.entries(nested).sort(([left], [right]) => compareCodePoints(left, right)))
                : nested
        ) ?? 'null'
    );
}

export function isSameValue(left: unknown, right: unknown): boolean {
    return stableStringify(left) === stableStringify(right);
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function compareCodePoints(left: string, right: string): number {
    if (left === right) return 0;
    return left < right ? -1 : 1;
}
