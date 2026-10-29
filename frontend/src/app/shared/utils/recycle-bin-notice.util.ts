import { pluralize } from './pluralize.util';

/**
 * Plain sentence (no HTML) for a delete confirmation of something that moves to the recycle bin.
 *
 *  recycleBinNotice(7)    → 'It moves to the recycle bin, where you can restore it for 7 days.'
 *  recycleBinNotice(1)    → 'It moves to the recycle bin, where you can restore it for 1 day.'
 *  recycleBinNotice(7, 3) → 'They move to the recycle bin, where you can restore them for 7 days.'
 *  recycleBinNotice(null) → 'It moves to the recycle bin, where you can restore it.'
 */
export function recycleBinNotice(retentionDays: number | null, itemCount: number = 1): string {
    const several = itemCount > 1;
    const subject = several ? 'They move' : 'It moves';
    const object = several ? 'them' : 'it';
    const period = retentionDays === null ? '' : ` for ${pluralize(retentionDays, 'day', 'days')}`;
    return `${subject} to the recycle bin, where you can restore ${object}${period}.`;
}

/**
 * Success toast (plain text) of a delete that moved items to the recycle bin. One wording for every kind of item.
 *
 *  movedToRecycleBinMessage(1, 'agent', 'agents')   → 'Moved 1 agent to the recycle bin.'
 *  movedToRecycleBinMessage(3, 'secret', 'secrets') → 'Moved 3 secrets to the recycle bin.'
 */
export function movedToRecycleBinMessage(count: number, singular: string, plural: string): string {
    return `Moved ${pluralize(count, singular, plural)} to the recycle bin.`;
}
