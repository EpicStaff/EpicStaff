import { MIN_COLUMN_WIDTH } from './table-layout-storage';

/**
 * Shares `available` px out among columns that need `contentWidths` px each (never less than MIN_COLUMN_WIDTH).
 * When they fit, every column gets its content width plus an equal share of what is left, so they fill `available`
 * exactly. When they don't, narrow columns keep their content width and the wide ones get one common cap that makes
 * the total `available`; if even MIN_COLUMN_WIDTH each is too much, the columns overflow and the table scrolls.
 */
export function fitColumnWidths(contentWidths: readonly number[], available: number): number[] {
    const content = contentWidths.map((width) => Math.max(MIN_COLUMN_WIDTH, Math.ceil(width)));
    const space = Math.floor(available);
    const total = content.reduce((sum, width) => sum + width, 0);
    if (total <= space) {
        return content.map((width, index) => width + shareOf(space - total, content.length, index));
    }
    // Water-filling: from the narrowest up, a column keeps its width while that is under an equal share of the rest.
    const byWidth = content.map((_width, index) => index).sort((first, second) => content[first] - content[second]);
    let remaining = space;
    let keptCount = 0;
    while (content[byWidth[keptCount]] * (content.length - keptCount) < remaining) {
        remaining -= content[byWidth[keptCount]];
        keptCount++;
    }
    const capped = new Set(byWidth.slice(keptCount));
    let cappedIndex = 0;
    return content.map((width, index) =>
        capped.has(index) ? Math.max(MIN_COLUMN_WIDTH, shareOf(remaining, capped.size, cappedIndex++)) : width
    );
}

/** The `index`-th of `count` near-equal integer parts of `total`: the first `total % count` parts are 1 px larger. */
function shareOf(total: number, count: number, index: number): number {
    const share = Math.floor(total / count);
    return share + (index < total - share * count ? 1 : 0);
}
