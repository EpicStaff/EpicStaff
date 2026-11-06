/**
 * LLM Library cards sit at most four to a row, 16px apart, and a row's cards fill its whole width (Figma: four
 * 318px cards across 1320px). A card never gets narrower than 318px: below that, a row holds one card fewer.
 */
export const LLM_LIBRARY_CARD_MIN_WIDTH = 318;
export const LLM_LIBRARY_CARD_GAP = 16;
export const LLM_LIBRARY_MAX_CARDS_PER_ROW = 4;

/** How many cards fit side by side in `containerWidth`; the maximum until the width is known, at least one. */
export function llmLibraryCardsPerRow(containerWidth: number | null): number {
    if (containerWidth === null) return LLM_LIBRARY_MAX_CARDS_PER_ROW;
    const fitting = Math.floor(
        (containerWidth + LLM_LIBRARY_CARD_GAP) / (LLM_LIBRARY_CARD_MIN_WIDTH + LLM_LIBRARY_CARD_GAP)
    );
    return Math.min(LLM_LIBRARY_MAX_CARDS_PER_ROW, Math.max(1, fitting));
}

/**
 * Puts provider groups on rows, in order: a group joins the current row when all its cards fit in the slots that row
 * has left, otherwise it starts a new row. A group with more cards than a row holds gets rows of its own (its cards
 * wrap), and the next group starts a new row after it.
 */
export function packLlmLibraryRows<T>(
    groups: readonly T[],
    cardCount: (group: T) => number,
    cardsPerRow: number
): T[][] {
    const rows: T[][] = [];
    let row: T[] = [];
    let usedSlots = 0;
    for (const group of groups) {
        const size = cardCount(group);
        if (row.length > 0 && usedSlots + size <= cardsPerRow) {
            row.push(group);
            usedSlots += size;
            continue;
        }
        if (row.length > 0) rows.push(row);
        row = [group];
        usedSlots = size;
    }
    if (row.length > 0) rows.push(row);
    return rows;
}

/** When a provider was added: the creation time of its earliest config (null when none recorded one) and its lowest config id. */
export interface ProviderCreationOrder {
    createdAt: number | null;
    lowestId: number;
}

export function providerCreationOrder(
    configs: readonly { id: number; createdAt: string | null }[]
): ProviderCreationOrder {
    let createdAt: number | null = null;
    let lowestId = Number.POSITIVE_INFINITY;
    for (const config of configs) {
        lowestId = Math.min(lowestId, config.id);
        const time = config.createdAt === null ? Number.NaN : Date.parse(config.createdAt);
        if (!Number.isNaN(time) && (createdAt === null || time < createdAt)) createdAt = time;
    }
    return { createdAt, lowestId };
}

/**
 * The provider added first comes first. A total order, so any mix sorts the same way: providers with a creation time
 * by that time, then those without one; ties, and providers without a time among themselves, by the lowest config id.
 */
export function compareProviderCreationOrder(first: ProviderCreationOrder, second: ProviderCreationOrder): number {
    if (first.createdAt !== null && second.createdAt !== null) {
        if (first.createdAt !== second.createdAt) return first.createdAt - second.createdAt;
    } else if (first.createdAt !== null) {
        return -1;
    } else if (second.createdAt !== null) {
        return 1;
    }
    return first.lowestId - second.lowestId;
}
