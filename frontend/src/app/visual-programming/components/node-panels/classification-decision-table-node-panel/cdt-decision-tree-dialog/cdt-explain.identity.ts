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
 * match. So these keys mirror what the server matches on, and a rule's key changes
 * when its `route_code` does, when it is renamed without one, or when another rule's
 * edit makes its code or name shared or unique.
 *
 * Losses are losses, never mix-ups — a confidently wrong explanation of someone
 * else's rule is far worse than a missing one. An edit to a rule's route code or
 * name in the grid carries that rule's explanations over to its new key
 * (`explainKeyMovesForRuleEdit`), except where a key is shared — see there. Any
 * other change of key loses the explanation: another rule the same edit re-keys (a
 * code or name it shared that the edit leaves unique, or the reverse), a deleted
 * rule that leaves its duplicate's code unique, and any other edit to a rule filed
 * by its content. Ambiguous rows (duplicate name, or a `route_code` shared between
 * rows, both of which this app permits) fall back to that content-derived key, so
 * they keep their explanation while untouched and can never be marked outdated by
 * an edit to what they contain.
 *
 * Pure and Angular-free, like the builder beside it.
 */

import { CdtExplainBlock } from '../../../../core/models/cdt-explain-api.model';
import { CdtExplanationKeyMove } from '../../../../core/models/classification-decision-table.model';
import { ConditionGroup } from '../../../../core/models/decision-table.model';
import { slugifyRouteCode } from '../cdt-route-continue.util';
import { enabledRowsInOrder } from './cdt-decision-tree.builder';
import { CdtDecisionTreeInput } from './cdt-decision-tree.model';

/**
 * Excluded because they say where the step sits, not what it does. Without this,
 * dragging a rule up the table would mark every rule below it outdated, and a
 * marker that fires on a reorder stops being read.
 */
const FINGERPRINT_EXCLUDED = ['id', 'order', 'on_no_match'] as const;

/** A rule's steps, each filed under `<rule key base>:<suffix>`. */
const RULE_STEP_SUFFIXES = ['decision', 'prompt', 'manipulation'] as const;

/**
 * How many drawn rules share each route slug and each name — whether a rule may
 * be keyed by either depends on it being the only one.
 */
interface RuleIdentityCounts {
    readonly routeSlugs: ReadonlyMap<string, number>;
    readonly names: ReadonlyMap<string, number>;
}

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
    const counts = countRuleIdentities(rows);

    rows.forEach((row, index) => {
        const base = ruleKeyBase(row, counts);
        for (const suffix of RULE_STEP_SUFFIXES) keys.set(`row-${index}:${suffix}`, `${base}:${suffix}`);
    });

    return keys;
}

/**
 * Every key an explanation on this table may still be wanted under — what decides
 * which stored explanations survive a write, never which one a step shows.
 *
 * Wider than `buildExplainStepKeys`, which only covers the rules the tree draws: a
 * hidden rule is still a rule, and its explanation has to be there when it is
 * shown again. Its key then depends on the rules it is shown alongside (a shared
 * code or name falls back to content), so each way it can come back is covered —
 * alone among the drawn rules, or with every hidden rule at once. Keeping a key
 * that turns out unused costs a few bytes; dropping a live one loses text.
 */
export function buildRetainedExplainStepKeys(input: CdtDecisionTreeInput): ReadonlySet<string> {
    const retained = new Set(buildExplainStepKeys(input).values());
    const hiddenRows = input.rows.filter((row) => row.dock_visible === false);
    if (hiddenRows.length === 0) return retained;

    const keysWithShown = (shown: (row: ConditionGroup) => boolean): void => {
        const rows = input.rows.map((row) => (shown(row) ? { ...row, dock_visible: true } : row));
        for (const key of buildExplainStepKeys({ ...input, rows }).values()) retained.add(key);
    };

    keysWithShown((row) => row.dock_visible === false);
    for (const hidden of hiddenRows) keysWithShown((row) => row === hidden);

    return retained;
}

/**
 * Where a rule's explanations go when an edit to its route code or name changes
 * the key they are filed under. `rowsBefore` and `rowsAfter` are the whole table
 * either side of the edit; only the rule at `rowIndex` differs between them.
 *
 * Left alone, the text would stay under the old key, where nothing reads it and
 * the next write drops it — paid for and silently gone. Moved, it shows again,
 * marked outdated where the step's content changed: a condition's fingerprint
 * covers the rule's route code and name, a prompt's and a manipulation's only its
 * name. So a prompt whose rule only changed route code moves and stays current,
 * which is what it is.
 *
 * Keys are worked out as `buildExplainStepKeys` works them out, among the drawn
 * rules. A hidden rule's are worked out as if it alone were shown again — the
 * first of the ways `buildRetainedExplainStepKeys` keeps a hidden rule's text.
 *
 * Nothing moves when another drawn rule resolves to either key after the edit.
 * Only identical rules share a key (a content key), and they share its one
 * explanation: taking it from under the old key would leave the rule still drawn
 * with it showing nothing, and writing over the new one would replace the current
 * text of the rules this one now duplicates with its own outdated text. Hidden
 * rules are not asked: what they resolve to depends on what they are shown
 * alongside, and the text under the edited rule's key is the edited rule's.
 *
 * Only this rule's keys move. The edit can change another rule's key too — a
 * shared code that becomes unique — and that rule's text is left where it is.
 */
export function explainKeyMovesForRuleEdit(
    rowsBefore: readonly ConditionGroup[],
    rowsAfter: readonly ConditionGroup[],
    rowIndex: number
): CdtExplanationKeyMove[] {
    const from = ruleKeyBaseAsShown(rowsBefore, rowIndex);
    const to = ruleKeyBaseAsShown(rowsAfter, rowIndex);
    if (from === null || to === null || from === to) return [];

    const edited = rowsAfter[rowIndex];
    const drawn = enabledRowsInOrder(rowsAfter);
    const counts = countRuleIdentities(drawn);
    const sharesAKey = drawn.some((row) => {
        if (row === edited) return false;
        const base = ruleKeyBase(row, counts);
        return base === from || base === to;
    });
    if (sharesAKey) return [];

    return RULE_STEP_SUFFIXES.map((suffix) => ({ from: `${from}:${suffix}`, to: `${to}:${suffix}` }));
}

/**
 * The key base of `rows[index]` among the drawn rules — or, for a hidden one,
 * among the drawn rules plus itself. Null when there is no such row.
 */
function ruleKeyBaseAsShown(rows: readonly ConditionGroup[], index: number): string | null {
    const row = rows[index];
    if (!row) return null;

    const drawn = enabledRowsInOrder(rows);
    return ruleKeyBase(row, countRuleIdentities(drawn.includes(row) ? drawn : [...drawn, row]));
}

function countRuleIdentities(drawnRows: readonly ConditionGroup[]): RuleIdentityCounts {
    return {
        // Counted on the slug, not the raw code, because the slug is what the key is
        // built from: `Approve` and `approve` each count as unique yet produce the same
        // key, which would hand one rule the other's explanation as current.
        routeSlugs: countBy(drawnRows, routeSlug),
        // Names are counted raw because the key and the server both use them raw.
        names: countBy(drawnRows, ruleName),
    };
}

/** A shared code or a duplicate name disqualifies that source rather than colliding. */
function ruleKeyBase(row: ConditionGroup, counts: RuleIdentityCounts): string {
    const slug = routeSlug(row);
    if (slug && counts.routeSlugs.get(slug) === 1) return `rule:route:${slug}`;

    const name = ruleName(row);
    if (name && counts.names.get(name) === 1) return `rule:name:${name}`;

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

function ruleName(row: ConditionGroup): string | null {
    return row.group_name?.trim() || null;
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
