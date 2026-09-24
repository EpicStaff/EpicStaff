/**
 * Identity and staleness for an explainable step.
 *
 * An explanation must outlive the step's *content* — that is the point of marking
 * one outdated rather than dropping it — so it cannot be filed under a hash of
 * that content. It needs a key that survives an edit, plus a fingerprint of what
 * it was generated from.
 *
 * There is no stable id for a rule anywhere in this stack: `ConditionGroup` has
 * none, and the backend's `condition_groups.id` is dropped on load, never sent
 * back, and would not help anyway — bulk save matches an incoming row by
 * `route_code`, else by `group_name`, and deletes plus recreates what it cannot
 * match. So these keys mirror what the server matches on, which makes every case
 * where an explanation is lost a case where the server also considers the row to
 * be a different row: a rename without a `route_code`, or a changed `route_code`.
 *
 * Losses are losses, never mix-ups — a confidently wrong explanation of someone
 * else's rule is far worse than a missing one. Ambiguous rows (duplicate name, or
 * a `route_code` shared between rows, both of which this app permits) fall back to
 * a content-derived key: they keep their explanation while untouched, lose it on
 * an edit, and can never be marked outdated.
 *
 * Pure and Angular-free, like the builder beside it.
 */

import { ConditionGroup } from '../../../../core/models/decision-table.model';
import { enabledRowsInOrder, slugifyRouteCode } from './cdt-decision-tree.builder';
import { CdtDecisionTreeInput } from './cdt-decision-tree.model';
import { CdtExplainBlock } from './cdt-explain.model';

/**
 * Excluded because they say where the step sits, not what it does. Without this,
 * dragging a rule up the table would mark every rule below it outdated, and a
 * marker that fires on a reorder stops being read.
 */
const FINGERPRINT_EXCLUDED = ['id', 'order', 'on_no_match'] as const;

/** What a step's explanation was generated from. */
export function explainStepFingerprint(block: CdtExplainBlock): string {
    const content: Record<string, unknown> = { ...block };
    for (const field of FINGERPRINT_EXCLUDED) delete content[field];
    return hash(stableStringify(content));
}

/**
 * Block id → the key its explanation is filed under.
 *
 * Not injective: the post-computation step is drawn once per exit column, so both
 * of its ids map to one key and share a single explanation.
 */
export function buildExplainStepKeys(input: CdtDecisionTreeInput): ReadonlyMap<string, string> {
    const keys = new Map<string, string>();

    if (input.preCode?.trim()) keys.set('spine:pre-computation', 'node:pre');
    if (input.postCode?.trim()) {
        keys.set('exit:default:post', 'node:post');
        keys.set('exit:route:post', 'node:post');
    }

    const rows = enabledRowsInOrder(input.rows);
    // Counted on the slug, not the raw code, because the slug is what the key is
    // built from: `Approve` and `approve` each count as unique yet produce the same
    // key, which would hand one rule the other's explanation as current.
    const routeSlugs = countBy(rows, (row) => routeSlug(row));
    // Names are counted raw because the key and the server both use them raw.
    const names = countBy(rows, (row) => row.group_name?.trim() || null);

    rows.forEach((row, index) => {
        const base = ruleKeyBase(row, routeSlugs, names);
        keys.set(`row-${index}:decision`, `${base}:decision`);
        keys.set(`row-${index}:prompt`, `${base}:prompt`);
        keys.set(`row-${index}:manipulation`, `${base}:manipulation`);
    });

    return keys;
}

/** A shared code or a duplicate name disqualifies that source rather than colliding. */
function ruleKeyBase(
    row: ConditionGroup,
    routeSlugs: ReadonlyMap<string, number>,
    names: ReadonlyMap<string, number>
): string {
    const slug = routeSlug(row);
    if (slug && routeSlugs.get(slug) === 1) return `rule:route:${slug}`;

    const name = row.group_name?.trim();
    if (name && names.get(name) === 1) return `rule:name:${name}`;

    return `rule:content:${hash(stableStringify(identifyingContent(row)))}`;
}

/** Listed rather than spread, so a new `ConditionGroup` field cannot change identity. */
function identifyingContent(row: ConditionGroup): Record<string, unknown> {
    return {
        group_name: row.group_name ?? '',
        expression: row.expression ?? '',
        field_expressions: row.field_expressions ?? {},
        manipulation: row.manipulation ?? '',
        field_manipulations: row.field_manipulations ?? {},
        prompt_id: row.prompt_id ?? '',
        route_code: row.route_code ?? '',
    };
}

function routeSlug(row: ConditionGroup): string | null {
    const code = row.route_code?.trim();
    return code ? slugifyRouteCode(code) : null;
}

function countBy<T>(items: readonly T[], pick: (item: T) => string | null): ReadonlyMap<string, number> {
    const counts = new Map<string, number>();
    for (const item of items) {
        const value = pick(item);
        if (value) counts.set(value, (counts.get(value) ?? 0) + 1);
    }
    return counts;
}

/** Keys sorted, because `field_expressions` comes from user input in any order. */
function stableStringify(value: unknown): string {
    if (value === null || typeof value !== 'object') return JSON.stringify(value) ?? 'null';
    if (Array.isArray(value)) return `[${value.map(stableStringify).join(',')}]`;

    const entries = Object.entries(value as Record<string, unknown>)
        .filter(([, v]) => v !== undefined)
        .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
        .map(([k, v]) => `${JSON.stringify(k)}:${stableStringify(v)}`);

    return `{${entries.join(',')}}`;
}

/**
 * Two 32-bit hashes and the length. Not security: it decides whether an
 * explanation is offered and whether it is stale, and one 32-bit hash collides too
 * readily across an editing session.
 */
function hash(input: string): string {
    let djb2 = 5381;
    let fnv = 0x811c9dc5;

    for (let i = 0; i < input.length; i++) {
        const code = input.charCodeAt(i);
        djb2 = (djb2 * 33) ^ code;
        fnv = Math.imul(fnv ^ code, 0x01000193);
    }

    return `${(djb2 >>> 0).toString(36)}${(fnv >>> 0).toString(36)}${input.length.toString(36)}`;
}
