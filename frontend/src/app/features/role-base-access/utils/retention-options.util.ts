import { SelectItem } from '@shared/components';
import { OrganizationRetention, OrganizationRetentionUpdate, RetentionDataType } from '@shared/models';

const DAYS_PER_YEAR = 365;

const RETENTION_DATA_TYPES: RetentionDataType[] = ['sessions', 'conversations', 'audit'];

// Lowering these removes stored data in the nightly purge; audit retention only applies to new events.
const PURGED_RETENTION_TYPES: RetentionDataType[] = ['sessions', 'conversations'];

/** The select value for "use the instance default"; app-select shows a null value as an empty placeholder. */
export const USE_DEFAULT_RETENTION = 'default';

export type RetentionChoice = number | typeof USE_DEFAULT_RETENTION;

export type RetentionField = `${RetentionDataType}_days`;

export type RetentionChoices = Record<RetentionField, RetentionChoice>;

export interface RetentionLowering {
    type: RetentionDataType;
    newEffectiveDays: number;
}

/** 0 → "Unlimited", 365 → "1 year", 730 → "2 years", 30 → "30 days". */
export function formatRetentionDays(days: number): string {
    if (days === 0) {
        return 'Unlimited';
    }
    if (days % DAYS_PER_YEAR === 0) {
        const years = days / DAYS_PER_YEAR;
        return years === 1 ? '1 year' : `${years} years`;
    }
    return days === 1 ? '1 day' : `${days} days`;
}

/** A stored value equal to the default is shown on the default option, which is the only option for that value. */
export function toRetentionChoice(days: number | null, defaultDays: number): RetentionChoice {
    return days === null || days === defaultDays ? USE_DEFAULT_RETENTION : days;
}

export function fromRetentionChoice(choice: RetentionChoice): number | null {
    return choice === USE_DEFAULT_RETENTION ? null : choice;
}

/**
 * The allowed values in policy order, the one equal to the default tagged "Default" and standing for "use the
 * instance default" (null), so the default value is never listed twice. A default outside the allowed values
 * leads the list. A stored value the policy no longer allows (the cap was lowered or the floor raised after it
 * was chosen) is kept as an extra option, so the select never shows blank.
 */
export function buildRetentionItems(
    retention: OrganizationRetention,
    type: RetentionDataType
): SelectItem<RetentionChoice>[] {
    const rule = retention.retention_policy[type];
    const defaultItem: SelectItem<RetentionChoice> = {
        name: formatRetentionDays(rule.default_days),
        tip: 'Default',
        value: USE_DEFAULT_RETENTION,
    };
    const items: SelectItem<RetentionChoice>[] = rule.allowed.map((days) =>
        days === rule.default_days ? defaultItem : { name: formatRetentionDays(days), value: days }
    );
    if (!rule.allowed.includes(rule.default_days)) {
        items.unshift(defaultItem);
    }

    const stored = retention[`${type}_days` as const];
    if (stored !== null && stored !== rule.default_days && !rule.allowed.includes(stored)) {
        const applied = retention[`${type}_effective_days` as const];
        // the backend raises a positive value below the floor to it; anything else outside `allowed` is over the cap
        const isBelowMinimum = rule.min_days !== null && stored > 0 && stored < rule.min_days;
        const bound = isBelowMinimum ? 'below minimum' : 'above limit';
        items.push({
            name: `${formatRetentionDays(stored)} (${bound}, ${applied} days applied)`,
            value: stored,
        });
    }
    return items;
}

/**
 * The changed types only, or null when nothing changed: an empty body is a 400, and a stored value
 * above a lowered cap is not in `allowed`, so unchanged types are never sent.
 */
export function buildRetentionUpdate(
    retention: OrganizationRetention,
    choices: RetentionChoices
): OrganizationRetentionUpdate | null {
    const update: OrganizationRetentionUpdate = {};
    for (const type of RETENTION_DATA_TYPES) {
        const field: RetentionField = `${type}_days`;
        const stored = retention[field];
        // a stored value equal to the default is shown as the default, so leaving it untouched keeps it as stored
        if (choices[field] === toRetentionChoice(stored, retention.retention_policy[type].default_days)) continue;
        update[field] = fromRetentionChoice(choices[field]);
    }
    return Object.keys(update).length > 0 ? update : null;
}

/** The purged types whose new effective days are lower than the current ones. */
export function findRetentionLowerings(
    retention: OrganizationRetention,
    update: OrganizationRetentionUpdate | null
): RetentionLowering[] {
    if (!update) return [];

    const lowerings: RetentionLowering[] = [];
    for (const type of PURGED_RETENTION_TYPES) {
        const chosen = update[`${type}_days`];
        if (chosen === undefined) continue;

        const newEffectiveDays = chosen ?? retention.retention_policy[type].default_days;
        const currentEffectiveDays = retention[`${type}_effective_days`];
        // 0 is unlimited: choosing it never removes data, and any finite value is lower than it
        const isLowered =
            newEffectiveDays !== 0 && (currentEffectiveDays === 0 || newEffectiveDays < currentEffectiveDays);
        if (isLowered) {
            lowerings.push({ type, newEffectiveDays });
        }
    }
    return lowerings;
}

/** "Sessions older than 30 days and conversations older than 90 days will be removed tonight. …" */
export function describeRetentionLowerings(lowerings: RetentionLowering[]): string {
    const sentence = lowerings
        .map((lowering) => `${lowering.type} older than ${lowering.newEffectiveDays} days`)
        .join(' and ');
    return `${sentence.charAt(0).toUpperCase()}${sentence.slice(1)} will be removed tonight. This cannot be undone.`;
}
