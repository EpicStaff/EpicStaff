/**
 * A count with the noun that fits it.
 *
 *  pluralize(1, 'flow', 'flows') → '1 flow'
 *  pluralize(3, 'flow', 'flows') → '3 flows'
 *  pluralize(0, 'flow', 'flows') → '0 flows'
 */
export function pluralize(count: number, singular: string, plural: string): string {
    return `${count} ${count === 1 ? singular : plural}`;
}
