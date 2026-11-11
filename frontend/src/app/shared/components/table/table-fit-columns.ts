import { MIN_COLUMN_WIDTH } from './table-layout-storage';

/** One column's claim on the width `distributeWidths` shares out. */
export interface WidthClaim {
    /** px the column starts from before it takes a share. */
    base: number;
    /** px it never goes under. */
    min: number;
    /** Its share of the width relative to the others, like the `n` of an `nfr` track; 0 takes no share. */
    weight: number;
}

/** Fractional px closer than this count as equal when the spare whole px are handed out. */
const FRACTION_TOLERANCE = 1e-9;

/**
 * Shares `available` px out among columns that need `contentWidths` px each (never less than MIN_COLUMN_WIDTH, never
 * more than `maxWidth`). When they fit, every column gets its content width plus an equal share of what is left, so
 * they fill `available` exactly; a column that reaches `maxWidth` stops there and the others share its part. If all
 * reach it the widths add up to less than `available`, and the table's filler column takes the rest. When they don't
 * fit, narrow columns keep their content width and the wide ones get one common cap that makes the total
 * `available`; if even MIN_COLUMN_WIDTH each is too much, the columns overflow and the table scrolls.
 */
export function fitColumnWidths(
    contentWidths: readonly number[],
    available: number,
    maxWidth: number = Number.POSITIVE_INFINITY
): number[] {
    const content = contentWidths.map((width) => Math.min(maxWidth, Math.max(MIN_COLUMN_WIDTH, Math.ceil(width))));
    const space = Math.floor(available);
    const total = content.reduce((sum, width) => sum + width, 0);
    if (total <= space) {
        return distributeWidths(
            content.map((width) => ({ base: width, min: width, weight: 1 })),
            space,
            maxWidth
        );
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

/**
 * Whole px widths adding up to `total`: column i gets `base + weight × u`, held between its `min` and `maxWidth` (a
 * `min` above `maxWidth` wins), with one `u` for all columns. With `base` 0 that is how CSS sizes `minmax(min, <weight>fr)`
 * tracks, under a cap; with `base` = `min` = a content width and weight 1, every column gets its content width plus
 * an equal share. When even the minimums exceed `total` they are returned as they are, and the columns overflow. When
 * every column that takes a share reaches `maxWidth` the widths add up to less than `total`. The px left over after
 * rounding go to the columns with the largest fractions, the first ones on a tie.
 */
export function distributeWidths(claims: readonly WidthClaim[], total: number, maxWidth: number): number[] {
    const ceilings = claims.map((claim) => Math.max(claim.min, maxWidth));
    const widthsAt = (level: number) =>
        claims.map((claim, index) => Math.min(ceilings[index], Math.max(claim.min, claim.base + claim.weight * level)));
    const sumAt = (level: number) => widthsAt(level).reduce((sum, width) => sum + width, 0);
    // The levels at which a column leaves its minimum or reaches its ceiling: between two of them the sum is linear.
    const breakpoints = [
        ...new Set(
            claims.flatMap((claim, index) =>
                claim.weight > 0
                    ? [(claim.min - claim.base) / claim.weight, (ceilings[index] - claim.base) / claim.weight]
                    : []
            )
        ),
    ]
        .filter((level) => level > 0 && Number.isFinite(level))
        .sort((first, second) => first - second);
    let level = 0;
    if (sumAt(level) >= total) return widthsAt(level);
    for (const next of [...breakpoints, Number.POSITIVE_INFINITY]) {
        const slope = claims.reduce((sum, claim, index) => {
            const width = claim.base + claim.weight * level;
            return claim.weight > 0 && width >= claim.min && width < ceilings[index] ? sum + claim.weight : sum;
        }, 0);
        if (slope > 0) {
            const reached = level + (total - sumAt(level)) / slope;
            if (reached <= next) return roundWidths(widthsAt(reached), total);
        }
        if (!Number.isFinite(next)) break;
        level = next;
    }
    // Every column that takes a share is at its ceiling.
    return widthsAt(level);
}

/** Rounds each width down, then gives the px that makes up `total` one each to the largest fractions. */
function roundWidths(widths: readonly number[], total: number): number[] {
    const rounded = widths.map((width) => Math.floor(width + FRACTION_TOLERANCE));
    const fraction = (index: number) => widths[index] - rounded[index];
    const spare = Math.round(total - rounded.reduce((sum, width) => sum + width, 0));
    const byFraction = widths
        .map((_width, index) => index)
        .sort((first, second) => {
            const difference = fraction(second) - fraction(first);
            return Math.abs(difference) > FRACTION_TOLERANCE ? difference : first - second;
        });
    byFraction.slice(0, spare).forEach((index) => rounded[index]++);
    return rounded;
}

/** The `index`-th of `count` near-equal integer parts of `total`: the first `total % count` parts are 1 px larger. */
function shareOf(total: number, count: number, index: number): number {
    const share = Math.floor(total / count);
    return share + (index < total - share * count ? 1 : 0);
}
