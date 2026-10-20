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

export function toRetentionChoice(days: number | null): RetentionChoice {
    return days === null ? USE_DEFAULT_RETENTION : days;
}

export function fromRetentionChoice(choice: RetentionChoice): number | null {
    return choice === USE_DEFAULT_RETENTION ? null : choice;
}

/**
 * "Use default" first, then the allowed values in policy order. A stored value the policy no longer
 * allows (its cap was lowered) is kept as an extra option, so the select never shows blank.
 */
export function buildRetentionItems(
    retention: OrganizationRetention,
    type: RetentionDataType
): SelectItem<RetentionChoice>[] {
    const rule = retention.retention_policy[type];
    const defaultLabel = rule.default_days === 0 ? 'Unlimited' : `${rule.default_days} days`;
    const items: SelectItem<RetentionChoice>[] = [
        { name: `Use default (${defaultLabel})`, value: USE_DEFAULT_RETENTION },
        ...rule.allowed.map((days) => ({ name: formatRetentionDays(days), value: days })),
    ];

    const stored = retention[`${type}_days` as const];
    if (stored !== null && !rule.allowed.includes(stored)) {
        const applied = retention[`${type}_effective_days` as const];
        items.push({
            name: `${formatRetentionDays(stored)} (above limit, ${applied} days applied)`,
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
        const chosen = fromRetentionChoice(choices[field]);
        if (chosen !== retention[field]) {
            update[field] = chosen;
        }
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
