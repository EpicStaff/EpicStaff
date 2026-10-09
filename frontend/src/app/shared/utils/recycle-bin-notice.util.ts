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
    const period = retentionDays === null ? '' : ` for ${retentionDays} ${retentionDays === 1 ? 'day' : 'days'}`;
    return `${subject} to the recycle bin, where you can restore ${object}${period}.`;
}
